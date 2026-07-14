import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models.article import Article
from app.models.brief import Brief
from app.models.brief_run import ArticleRun, ArticleRunStatus, BriefRun

logger = logging.getLogger(__name__)

DIGEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest")


def load_json_filter(value):
    """Jinja2 过滤器：安全读取 JSON 字符串，避免摘要解析失败时影响整份简报。"""

    try:
        return json.loads(value)
    except Exception:
        return {}


env = Environment(loader=FileSystemLoader("app/templates"))
env.filters["load_json"] = load_json_filter


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    """统一清洗关键词，保证标题、文件名和合并查询使用同一套关键词。"""

    return [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]


def _keyword_label(keywords: list[str] | None) -> str:
    """把关键词数组转换成人可读名称，多关键词使用中文顿号连接。"""

    return "、".join(_normalize_keywords(keywords))


def _normalize_article_ids(article_ids: list | None) -> list[int]:
    """兼容历史 JSON 数据，把文章 ID 统一转换为整数并去重保序。"""

    normalized: list[int] = []
    seen: set[int] = set()
    for value in article_ids or []:
        try:
            article_id = int(value)
        except (TypeError, ValueError):
            continue
        if article_id not in seen:
            normalized.append(article_id)
            seen.add(article_id)
    return normalized


def _build_brief_name(topic: str, brief_date: date, keywords: list[str] | None = None) -> str:
    """生成简报名称：主题_关键词_日期_简报；没有关键词时为主题_日期_简报。"""

    topic_label = (topic or "综合").strip() or "综合"
    keyword_text = _keyword_label(keywords)
    date_text = brief_date.strftime("%Y-%m-%d")
    parts = [topic_label]
    if keyword_text:
        parts.append(keyword_text)
    parts.extend([date_text, "简报"])
    return "_".join(parts)


def _group_articles_by_topic(article_runs: list[ArticleRun]) -> dict:
    """按 AI 分类主题分组，用于模板分区展示文章。"""

    grouped = defaultdict(list)
    for item in article_runs:
        grouped[item.classified_topic or item.source_topic or "其他"].append(item)
    return grouped


def _safe_filename(value: str) -> str:
    """将标题转换为安全文件名，避免不同关键词简报互相覆盖 HTML 文件。"""

    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (value or "综合"))
    return safe.strip("_") or "综合"


def _save_digest_file(
    brief_date: date,
    html_content: str,
    topic: str = "综合",
    keywords: list[str] | None = None,
) -> str:
    """将简报 HTML 落盘到 digest 目录，文件名与简报名称保持一致。"""

    os.makedirs(DIGEST_DIR, exist_ok=True)
    brief_name = _build_brief_name(topic, brief_date, keywords)
    file_path = os.path.join(DIGEST_DIR, f"{_safe_filename(brief_name)}.html")
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(html_content)
    return file_path


def _render_brief_html(
    brief_date: date,
    topic: str,
    article_runs: list[ArticleRun],
    keywords: list[str] | None,
) -> str:
    """渲染简报 HTML，标题和副标题都带上关键词信息。"""

    template = env.get_template("brief.html")
    clean_keywords = _normalize_keywords(keywords)
    grouped_articles = _group_articles_by_topic(article_runs)
    return template.render(
        date=brief_date.strftime("%Y-%m-%d"),
        date_label=brief_date.strftime("%Y-%m-%d"),
        report_title=_build_brief_name(topic, brief_date, clean_keywords),
        subtitle=f"主题：{topic}" + (f" | 关键词：{_keyword_label(clean_keywords)}" if clean_keywords else ""),
        grouped_articles=grouped_articles,
        total_count=len(article_runs),
    )


def _pick_prior_article_run(
    runs: list[ArticleRun],
    existing_brief: Brief,
) -> ArticleRun | None:
    """从旧简报关联的历史运行结果中选择最合适的一条，优先使用旧简报原 run 的 AI 结果。"""

    if not runs:
        return None

    if existing_brief.brief_run_id:
        for run in runs:
            if run.brief_run_id == existing_brief.brief_run_id:
                return run

    # 历史兼容：如果旧简报没有 brief_run_id，就使用最新的已处理结果。
    return sorted(runs, key=lambda item: item.updated_at or item.created_at or datetime.min, reverse=True)[0]


def _merge_article_runs_for_brief(
    db: Session,
    current_runs: list[ArticleRun],
    existing_brief: Brief | None,
) -> list[ArticleRun]:
    """合并旧简报文章和本次新增文章，防止增量生成时旧内容被覆盖丢失。"""

    old_ids = _normalize_article_ids(existing_brief.article_ids if existing_brief else [])
    merged_order: list[int] = []
    merged_runs: dict[int, ArticleRun] = {}

    if old_ids:
        prior_runs = (
            db.query(ArticleRun)
            .options(joinedload(ArticleRun.article))
            .filter(
                ArticleRun.article_id.in_(old_ids),
                ArticleRun.status == ArticleRunStatus.processed,
            )
            .all()
        )
        prior_by_article: dict[int, list[ArticleRun]] = defaultdict(list)
        for run in prior_runs:
            prior_by_article[run.article_id].append(run)

        fallback_articles = {
            article.id: article
            for article in db.query(Article).filter(Article.id.in_(old_ids)).all()
        }

        for article_id in old_ids:
            chosen = _pick_prior_article_run(prior_by_article.get(article_id, []), existing_brief)
            if chosen is None and article_id in fallback_articles:
                # 历史旧数据可能没有 ArticleRun，这里构造临时展示项，保证旧文章不会被增量生成吞掉。
                chosen = ArticleRun(
                    article_id=article_id,
                    article=fallback_articles[article_id],
                    source_topic=existing_brief.topic,
                    status=ArticleRunStatus.processed,
                )
            if chosen:
                merged_order.append(article_id)
                merged_runs[article_id] = chosen

    for run in current_runs:
        if not run.article_id:
            continue
        if run.article_id not in merged_order:
            merged_order.append(run.article_id)
        # 本次运行的 AI 结果更新，优先覆盖历史同文章结果。
        merged_runs[run.article_id] = run

    return [merged_runs[article_id] for article_id in merged_order if article_id in merged_runs]


def generate_brief_for_run(run_id: int) -> Brief | None:
    """基于某次运行生成或更新简报。

    技术原则：
    1. 同一天、同主题、同关键词只有一份有效简报。
    2. 再次生成时合并旧简报文章和本次新增文章，再整体重渲染。
    3. 同主题不同关键词依赖 keywords_hash 隔离，不互相覆盖。
    """

    db = SessionLocal()
    try:
        brief_run = (
            db.query(BriefRun)
            .options(joinedload(BriefRun.article_runs).joinedload(ArticleRun.article))
            .filter(BriefRun.id == run_id)
            .first()
        )
        if brief_run is None:
            logger.warning("未找到简报运行实例: run_id=%s", run_id)
            return None

        current_runs = [
            item
            for item in brief_run.article_runs
            if item.status == ArticleRunStatus.processed
        ]
        if not current_runs:
            logger.info("No articles to generate brief for topic %s.", brief_run.topic)
            return None

        existing_brief = (
            db.query(Brief)
            .filter(
                Brief.date == brief_run.run_date,
                Brief.topic == brief_run.topic,
                Brief.keywords_hash == brief_run.keywords_hash,
                Brief.is_deleted == False,
            )
            .first()
        )

        article_runs = _merge_article_runs_for_brief(db, current_runs, existing_brief)
        if not article_runs:
            logger.info("No merged articles to generate brief for topic %s.", brief_run.topic)
            return None

        html_content = _render_brief_html(
            brief_date=brief_run.run_date,
            topic=brief_run.topic,
            article_runs=article_runs,
            keywords=brief_run.keywords or [],
        )
        article_ids = [item.article_id for item in article_runs]
        brief_title = _build_brief_name(brief_run.topic, brief_run.run_date, brief_run.keywords or [])

        if existing_brief:
            logger.info(
                "Merge update brief id=%s date=%s topic=%s keywords_hash=%s old_count=%s new_count=%s merged_count=%s.",
                existing_brief.id,
                brief_run.run_date,
                brief_run.topic,
                brief_run.keywords_hash,
                len(existing_brief.article_ids or []),
                len(current_runs),
                len(article_runs),
            )
            existing_brief.title = brief_title
            existing_brief.html_content = html_content
            existing_brief.article_ids = article_ids
            existing_brief.keywords = brief_run.keywords or []
            existing_brief.keywords_hash = brief_run.keywords_hash
            existing_brief.run_key = brief_run.run_key
            existing_brief.brief_run_id = brief_run.id
            existing_brief.generated_at = datetime.utcnow()
            brief = existing_brief
        else:
            brief = Brief(
                date=brief_run.run_date,
                title=brief_title,
                topic=brief_run.topic,
                brief_type="daily",
                html_content=html_content,
                article_ids=article_ids,
                keywords=brief_run.keywords or [],
                keywords_hash=brief_run.keywords_hash,
                run_key=brief_run.run_key,
                brief_run_id=brief_run.id,
            )
            db.add(brief)

        db.commit()
        db.refresh(brief)
        _save_digest_file(brief_run.run_date, html_content, brief_run.topic, brief_run.keywords or [])
        return brief
    except Exception as exc:
        logger.error("Error generating brief: %s", exc, exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()


def generate_briefs_for_runs(run_ids: list[int]) -> list[Brief]:
    """批量生成多份简报；每个 run 会按自己的主题和关键词独立合并。"""

    briefs = []
    for run_id in run_ids:
        brief = generate_brief_for_run(run_id)
        if brief:
            briefs.append(brief)
    return briefs
