import json
import logging
import os
from collections import defaultdict
from datetime import date

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models.brief import Brief
from app.models.brief_run import ArticleRun, ArticleRunStatus, BriefRun

logger = logging.getLogger(__name__)

DIGEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest")


def load_json_filter(value):
    """Jinja2 过滤器：安全读取 JSON 字符串。"""

    try:
        return json.loads(value)
    except Exception:
        return {}


env = Environment(loader=FileSystemLoader("app/templates"))
env.filters["load_json"] = load_json_filter


def _group_articles_by_topic(article_runs: list[ArticleRun]) -> dict:
    """按分类主题分组。"""

    grouped = defaultdict(list)
    for item in article_runs:
        grouped[item.classified_topic or item.source_topic or "其他"].append(item)
    return grouped


def _safe_topic_filename(topic: str) -> str:
    """将主题转为安全文件名。"""

    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (topic or "综合"))
    return safe.strip("_") or "综合"


def _save_digest_file(brief_date: date, html_content: str, topic: str = "综合") -> str:
    """将简报 HTML 落盘到 digest 目录。"""

    os.makedirs(DIGEST_DIR, exist_ok=True)
    topic_name = _safe_topic_filename(topic)
    file_path = os.path.join(DIGEST_DIR, f"{topic_name}_brief_{brief_date.strftime('%Y-%m-%d')}.html")
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(html_content)
    return file_path


def _render_brief_html(brief_date: date, topic: str, article_runs: list[ArticleRun], keywords: list[str] | None) -> str:
    """渲染简报 HTML。"""

    template = env.get_template("brief.html")
    grouped_articles = _group_articles_by_topic(article_runs)
    return template.render(
        date=brief_date.strftime("%Y-%m-%d"),
        date_label=brief_date.strftime("%Y-%m-%d"),
        report_title=f"IntelliBrief {topic}每日简报",
        subtitle=f"主题：{topic}" + (f" | 关键词：{'、'.join(keywords)}" if keywords else ""),
        grouped_articles=grouped_articles,
        total_count=len(article_runs),
    )


def generate_brief_for_run(run_id: int) -> Brief | None:
    """基于某次运行生成简报。

    原理：
    1. 一次运行只读取自己的 article_runs。
    2. 因此多人同时生成同一主题、不同关键词，不会互相串数据。
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

        article_runs = [
            item
            for item in brief_run.article_runs
            if item.status == ArticleRunStatus.processed
        ]
        if not article_runs:
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
        if existing_brief:
            db.delete(existing_brief)
            db.commit()

        html_content = _render_brief_html(
            brief_date=brief_run.run_date,
            topic=brief_run.topic,
            article_runs=article_runs,
            keywords=brief_run.keywords or [],
        )
        article_ids = [item.article_id for item in article_runs]

        brief = Brief(
            date=brief_run.run_date,
            title=f"IntelliBrief {brief_run.topic}每日简报 - {brief_run.run_date.strftime('%Y-%m-%d')}",
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
        _save_digest_file(brief_run.run_date, html_content, brief_run.topic)
        return brief
    except Exception as exc:
        logger.error("Error generating brief: %s", exc, exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()


def generate_briefs_for_runs(run_ids: list[int]) -> list[Brief]:
    """批量生成多份简报。"""

    briefs = []
    for run_id in run_ids:
        brief = generate_brief_for_run(run_id)
        if brief:
            briefs.append(brief)
    return briefs
