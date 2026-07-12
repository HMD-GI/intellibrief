import asyncio
import json
import logging
from itertools import combinations
from typing import Iterable

from app.models.article import Article
from app.models.brief_run import ArticleRun, ArticleRunStatus
from processor.prompts import build_glm_classify_prompt, build_glm_filter_prompt, build_summary_prompt
from utils.llm_router import AllLLMKeysFailedError, llm_router

logger = logging.getLogger(__name__)

MAX_LLM_CONCURRENCY = 8


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    """规整关键词，去重去空。"""

    seen = set()
    normalized = []
    for keyword in keywords or []:
        value = (keyword or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _build_filter_groups(topic: str, keywords: list[str] | None) -> list[list[str]]:
    """构造主题+关键词组合。

    原理：
    1. 主题是必选项。
    2. 关键词如果存在，则生成所有“至少包含一个关键词”的组合。
    3. 这样大模型既能匹配完整意图，也能匹配部分关键词命中的文章。
    """

    normalized_topic = (topic or "").strip()
    normalized_keywords = _normalize_keywords(keywords)
    if not normalized_topic:
        return []
    if not normalized_keywords:
        return [[normalized_topic]]

    groups: list[list[str]] = []
    for size in range(len(normalized_keywords), 0, -1):
        for combo in combinations(normalized_keywords, size):
            groups.append([normalized_topic, *combo])
    return groups


async def _filter_one_article(article: Article, topic: str, keywords: list[str] | None = None) -> tuple[Article, bool, int]:
    """单篇文章第一步筛选。"""

    first_paragraph = article.content[:500] if article.content else ""
    filter_groups = _build_filter_groups(topic, keywords)
    prompt = build_glm_filter_prompt(article.title, first_paragraph, topic, filter_groups)
    messages = [{"role": "user", "content": prompt}]
    response_text = await llm_router.call_llm_async(
        provider="first",
        messages=messages,
        response_format={"type": "json_object"},
    )
    result = json.loads(response_text)
    return article, bool(result.get("relevant")), int(result.get("score", 0) or 0)


async def _summary_one_article(article: Article) -> tuple[Article, dict]:
    """单篇文章摘要。"""

    content = article.content[:3000] if article.content else ""
    prompt = build_summary_prompt(content)
    messages = [{"role": "user", "content": prompt}]
    response_text = await llm_router.call_llm_async(
        provider="second",
        messages=messages,
        response_format={"type": "json_object"},
    )
    return article, json.loads(response_text)


async def _classify_one_article(article: Article) -> tuple[Article, str]:
    """单篇文章分类。"""

    prompt = build_glm_classify_prompt(article.title, article.tags or "")
    messages = [{"role": "user", "content": prompt}]
    response_text = await llm_router.call_llm_async(provider="third", messages=messages)
    return article, (response_text or "").strip()


async def _run_batched(tasks: Iterable, limit: int = MAX_LLM_CONCURRENCY):
    """限制并发的异步批量执行器。"""

    semaphore = asyncio.Semaphore(limit)

    async def _wrapped(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*[_wrapped(task) for task in tasks], return_exceptions=True)


def _apply_summary(article_run: ArticleRun, result: dict) -> None:
    """回写摘要结果。"""

    article_run.summary = json.dumps(
        {
            "one_liner": result.get("one_liner", ""),
            "key_points": result.get("key_points", []),
        },
        ensure_ascii=False,
    )
    article_run.tags = ",".join(result.get("tags", []))


async def process_article_runs_async(
    article_runs: list[ArticleRun],
    topic: str,
    keywords: list[str] | None = None,
) -> tuple[list[ArticleRun], list[ArticleRun]]:
    """按运行实例异步处理文章。

    返回值：
    1. 通过筛选的 article_runs
    2. 被过滤掉的 article_runs
    """

    if not article_runs:
        return [], []

    normalized_keywords = _normalize_keywords(keywords)
    filter_jobs = [
        _filter_one_article(item.article, topic=topic, keywords=normalized_keywords)
        for item in article_runs
    ]
    filter_results = await _run_batched(filter_jobs)

    run_by_article_id = {item.article_id: item for item in article_runs}
    passed_runs: list[ArticleRun] = []
    dropped_runs: list[ArticleRun] = []

    for result in filter_results:
        if isinstance(result, AllLLMKeysFailedError):
            raise result
        if isinstance(result, Exception):
            logger.error("文章筛选失败: %s", result)
            continue
        article, relevant, score = result
        article_run = run_by_article_id.get(article.id)
        if article_run is None:
            continue
        article_run.score = score
        if relevant and score >= 60:
            passed_runs.append(article_run)
            logger.info(
                "Filter result: title=%s..., relevant=%s, score=%s, keywords=%s",
                article.title[:60],
                relevant,
                score,
                normalized_keywords,
            )
        else:
            article_run.status = ArticleRunStatus.filtered
            dropped_runs.append(article_run)
            logger.info(
                "Filter dropped: title=%s..., reason=%s",
                article.title[:60],
                "irrelevant" if not relevant else "score_below_60",
            )

    if not passed_runs:
        return passed_runs, dropped_runs

    summary_results = await _run_batched([_summary_one_article(item.article) for item in passed_runs])
    for result in summary_results:
        if isinstance(result, AllLLMKeysFailedError):
            raise result
        if isinstance(result, Exception):
            logger.error("文章摘要失败: %s", result)
            continue
        article, summary_payload = result
        article_run = run_by_article_id.get(article.id)
        if article_run is None:
            continue
        _apply_summary(article_run, summary_payload)

    classify_results = await _run_batched([_classify_one_article(item.article) for item in passed_runs])
    for result in classify_results:
        if isinstance(result, AllLLMKeysFailedError):
            raise result
        if isinstance(result, Exception):
            logger.error("文章分类失败: %s", result)
            continue
        article, classified_topic = result
        article_run = run_by_article_id.get(article.id)
        if article_run is None:
            continue
        article_run.classified_topic = classified_topic
        article_run.status = ArticleRunStatus.processed

    return passed_runs, dropped_runs
