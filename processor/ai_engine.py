import json  # 导入 json 模块，用于解析大模型响应
import logging  # 导入日志模块
from concurrent.futures import ThreadPoolExecutor, as_completed  # 导入线程池，用于并发调用大模型
from itertools import combinations  # 导入组合工具，用于生成关键词组合
from typing import List  # 导入类型注解
from app.models.article import Article  # 导入文章模型
from utils.llm_router import AllLLMKeysFailedError, llm_router  # 导入大模型路由器
from processor.prompts import build_glm_classify_prompt, build_glm_filter_prompt, build_summary_prompt  # 导入提示词构造函数

logger = logging.getLogger(__name__)  # 初始化日志记录器
MAX_LLM_WORKERS = 6  # 大模型并发线程数上限，避免一次性压垮 API


def _worker_count(total: int) -> int:  # 根据文章数量动态计算线程数
    return max(1, min(MAX_LLM_WORKERS, total))  # 至少 1 个线程，最多不超过上限


def _normalize_keywords(keywords: list[str] | None) -> list[str]:  # 规整关键词列表
    seen = set()
    normalized = []
    for keyword in keywords or []:
        value = (keyword or "").strip()  # 去掉空值和首尾空白
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _build_filter_groups(topic: str, keywords: list[str] | None) -> list[list[str]]:  # 构建主题和关键词组合
    normalized_topic = (topic or "").strip()  # 主题是必选项
    normalized_keywords = _normalize_keywords(keywords)
    if not normalized_topic:
        return []
    if not normalized_keywords:
        return [[normalized_topic]]  # 没有关键词时只使用主题

    groups: list[list[str]] = []
    for size in range(len(normalized_keywords), 0, -1):  # 先生成更完整的组合，再生成较小组合
        for combo in combinations(normalized_keywords, size):
            groups.append([normalized_topic, *combo])  # 每一组都必须带主题
    return groups


def _filter_one_article(article: Article, keywords: list[str] | None = None) -> tuple[Article, bool, int]:  # 单篇文章筛选
    first_paragraph = article.content[:500] if article.content else ""  # 取前 500 字作为首段内容
    topic = (
        article.topic
        or (article.source.topics if getattr(article, "source", None) and getattr(article.source, "topics", None) else "")
    )  # 主题只取文章主题或数据源主题
    filter_groups = _build_filter_groups(topic, keywords)  # 生成主题和关键词组合
    prompt = build_glm_filter_prompt(article.title, first_paragraph, topic, filter_groups)  # 构建第一步筛选提示词
    messages = [{"role": "user", "content": prompt}]  # 构建消息上下文
    response_text = llm_router.call_llm(
        provider="first",  # 第一步使用 FIRST_LLM_* 配置
        messages=messages,
        response_format={"type": "json_object"}  # 要求返回 JSON
    )
    result = json.loads(response_text)  # 解析大模型返回结果
    return article, bool(result.get("relevant")), int(result.get("score", 0) or 0)


def _summary_one_article(article: Article) -> tuple[Article, dict]:  # 单篇文章摘要
    content = article.content[:3000] if article.content else ""  # 截取前 3000 字，避免 token 超限
    prompt = build_summary_prompt(content)  # 构建摘要提示词
    messages = [{"role": "user", "content": prompt}]
    response_text = llm_router.call_llm(
        provider="second",  # 第二步使用 SECOND_LLM_* 配置
        messages=messages,
        response_format={"type": "json_object"}
    )
    return article, json.loads(response_text)


def _classify_one_article(article: Article) -> tuple[Article, str]:  # 单篇文章分类
    prompt = build_glm_classify_prompt(article.title, article.tags or "")  # 构建分类提示词
    messages = [{"role": "user", "content": prompt}]
    response_text = llm_router.call_llm(provider="third", messages=messages)  # 第三步使用 THIRD_LLM_* 配置
    return article, (response_text or "").strip()


def filter_articles(articles: List[Article], keywords: list[str] | None = None) -> List[Article]:  # 第一步筛选文章
    filtered = []
    normalized_keywords = _normalize_keywords(keywords)  # 统一规整关键词，避免每篇文章重复处理脏数据
    if not articles:
        return filtered
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [
            executor.submit(_filter_one_article, article, normalized_keywords) for article in articles
        ]  # 并发提交筛选任务
        for future in as_completed(futures):
            try:
                article, relevant, score = future.result()
                article.quality_score = score  # 主线程回写 ORM 对象
                logger.info(
                    f"Filter result: title={article.title[:60]}..., relevant={relevant}, score={score}, keywords={normalized_keywords}"
                )  # 记录每篇文章的筛选结果和本次关键词
                if relevant and score >= 60:
                    filtered.append(article)  # 判定通过则保留
                else:
                    logger.info(
                        f"Filter dropped: title={article.title[:60]}..., reason={'irrelevant' if not relevant else 'score_below_60'}"
                    )  # 记录未通过原因
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()  # 所有 Key 不可用时取消剩余任务
                raise
            except Exception as e:
                logger.error(f"Error filtering article: {e}")  # 单篇失败不阻断其余文章
    return filtered


def generate_summary(article: Article) -> None:  # 兼容单篇摘要调用
    try:
        target, result = _summary_one_article(article)
        _apply_summary_result(target, result)  # 回写摘要结果
    except AllLLMKeysFailedError:
        raise
    except Exception as e:
        logger.error(f"Error generating summary for article {article.id}: {e}")


def _apply_summary_result(article: Article, result: dict) -> None:  # 将摘要结果写回文章对象
    article.summary = json.dumps({
        "one_liner": result.get("one_liner", ""),
        "key_points": result.get("key_points", [])
    }, ensure_ascii=False)  # 保存摘要 JSON，保留中文
    article.tags = ",".join(result.get("tags", []))  # 标签列表转逗号分隔字符串


def generate_summaries(articles: List[Article]) -> None:  # 并发生成摘要
    if not articles:
        return
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [executor.submit(_summary_one_article, article) for article in articles]
        for future in as_completed(futures):
            try:
                article, result = future.result()
                _apply_summary_result(article, result)
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()
                raise
            except Exception as e:
                logger.error(f"Error generating summary: {e}")


def classify_articles(articles: List[Article]) -> None:  # 并发执行第三步分类
    if not articles:
        return
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [executor.submit(_classify_one_article, article) for article in articles]
        for future in as_completed(futures):
            try:
                article, topic = future.result()
                article.topic = topic  # 回写最终分类主题
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()
                raise
            except Exception as e:
                logger.error(f"Error classifying article: {e}")
