import asyncio
import hashlib
import json
import logging
import os
from datetime import date, datetime
from urllib.parse import urlparse

import requests
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal, ensure_sqlite_schema
from app.models.article import Article, ArticleStatus
from app.models.brief import Brief
from app.models.brief_run import ArticleRun, ArticleRunStatus, BriefRun, BriefRunStatus
from app.models.source import Source
from app.models.setting import AppSetting
from app.modules.notification import (
    load_binding_settings,
    send_email,
    send_feishu_robot_card,
    should_fetch_weather,
)
from app.modules.weather import WeatherServiceError, weather_service
from brief.generator import generate_briefs_for_runs
from crawlers import get_crawler
from processor.ai_engine import process_article_runs_async
from processor.cleaner import extract_clean_content, extract_first_image_url
from processor.dedup import load_latest_crawl_cursor, save_latest_crawl_cursor
from scheduler.celery_app import celery_app
from utils.llm_router import AllLLMKeysFailedError, llm_router

logger = logging.getLogger(__name__)
ensure_sqlite_schema()

PHOTO_ROOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "photo")


def _guess_image_ext(image_url: str, content_type: str | None) -> str:
    """猜测图片扩展名。"""

    if content_type:
        ct = content_type.lower()
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
        if "gif" in ct:
            return ".gif"
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
    try:
        path = urlparse(image_url).path
        _, ext = os.path.splitext(path)
        if ext and len(ext) <= 5:
            return ext
    except Exception:
        pass
    return ".jpg"


def _image_no_exists(day_dir: str, image_no: int) -> bool:
    """判断当日目录下是否已存在相同编号图片。"""

    prefix = f"{image_no}."
    return any(filename.startswith(prefix) for filename in os.listdir(day_dir))


def _download_and_save_image(article_url: str, raw_html: str, date_str: str, image_url: str | None = None) -> tuple[int | None, str | None]:
    """下载并保存文章图片。"""

    try:
        image_url = image_url or extract_first_image_url(raw_html, article_url)
        if not image_url:
            return None, None

        day_dir = os.path.join(PHOTO_ROOT_DIR, date_str)
        os.makedirs(day_dir, exist_ok=True)
        existing_numbers = []
        for name in os.listdir(day_dir):
            stem, _ = os.path.splitext(name)
            if stem.isdigit():
                existing_numbers.append(int(stem))
        image_no = (max(existing_numbers) + 1) if existing_numbers else 1

        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(image_url, headers=headers, timeout=15)
        if response.status_code != 200 or not response.content:
            return None, None

        ext = _guess_image_ext(image_url, response.headers.get("Content-Type"))
        while _image_no_exists(day_dir, image_no):
            image_no += 1

        filename = f"{image_no}{ext}"
        file_path = os.path.join(day_dir, filename)
        with open(file_path, "wb") as file:
            file.write(response.content)
        return image_no, f"/photo/{date_str}/{filename}"
    except Exception as exc:
        logger.error("_download_and_save_image failed: %s", exc, exc_info=True)
        return None, None


def _normalize_topics(topics: list[str] | None) -> list[str]:
    """规整主题列表。"""

    return [topic.strip() for topic in (topics or []) if topic and topic.strip()]


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    """规整关键词列表。"""

    return [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]


def _load_weather_preferences(db) -> dict:
    """读取天气偏好配置。"""

    row = db.query(AppSetting).filter(AppSetting.key == "weather_preferences").first()
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except Exception:
        return {}


def _keywords_hash(topic: str, keywords: list[str] | None) -> str:
    """生成主题+关键词稳定哈希。"""

    payload = {
        "topic": (topic or "").strip(),
        "keywords": sorted(_normalize_keywords(keywords)),
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _build_run_key(topic: str, keywords: list[str] | None) -> str:
    """生成一次运行的唯一键。"""

    now = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"{date.today().isoformat()}:{topic}:{_keywords_hash(topic, keywords)}:{now}"


def _load_active_source_topics() -> list[str]:
    """读取所有启用数据源主题。"""

    db = SessionLocal()
    try:
        return [
            row[0]
            for row in db.query(Source.topics).filter(Source.is_active == True, Source.topics != "").distinct().all()
        ]
    finally:
        db.close()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """解析 ISO 时间字符串。"""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _pick_effective_article_date(items: list) -> str | None:
    """???????????????????

    ?????
    1. ??????????????????????????
    2. ????????????????????????

    ???????
    1. ??????????????
    2. ?????????????????? AI ?????????
    """

    today_str = date.today().isoformat()
    article_dates: list[str] = []
    for item in items or []:
        article_date = None
        if isinstance(item, dict):
            article_date = item.get("article_date") or (item.get("published_date", "")[:10] if item.get("published_date") else None)
        else:
            article_date = getattr(item, "article_date", None) or (
                item.published_date.isoformat()[:10] if getattr(item, "published_date", None) else None
            )
        if article_date:
            article_dates.append(article_date)
    if not article_dates:
        return None
    if today_str in article_dates:
        return today_str
    return max(article_dates)


def _filter_new_articles_by_cursor(raw_articles: list, source: Source, topic: str, keywords: list[str] | None) -> list:
    """基于 Redis 游标过滤仅新增文章。

    原理：
    1. Redis 记录该主题+关键词最近一次抓到的最新发布时间。
    2. 本次抓取只保留发布时间晚于该游标的文章。
    3. 如果发布时间相同，则用标题和 URL 做补充判断。
    """

    cursor = load_latest_crawl_cursor(source.id, topic, keywords)
    if not cursor:
        return raw_articles

    latest_dt = _parse_iso_datetime(cursor.get("published_at"))
    latest_url = cursor.get("url")
    latest_title = cursor.get("title")
    if not latest_dt:
        return raw_articles

    filtered = []
    for item in raw_articles:
        published_at = getattr(item, "published_date", None)
        if published_at and published_at > latest_dt:
            filtered.append(item)
            continue
        if published_at and published_at == latest_dt:
            if item.url != latest_url or item.title != latest_title:
                filtered.append(item)
    return filtered


def _ensure_article_run(db, brief_run: BriefRun, article: Article) -> ArticleRun:
    """确保某篇文章在本次运行中存在独立结果行。"""

    article_run = (
        db.query(ArticleRun)
        .filter(ArticleRun.brief_run_id == brief_run.id, ArticleRun.article_id == article.id)
        .first()
    )
    if article_run:
        return article_run

    article_run = ArticleRun(
        brief_run_id=brief_run.id,
        article_id=article.id,
        source_topic=article.source.topics if article.source and article.source.topics else None,
        status=ArticleRunStatus.pending,
    )
    db.add(article_run)
    db.flush()
    return article_run


def _backfill_today_articles_for_missing_brief(db, brief_run: BriefRun) -> int:
    """当日缺失简报时，将数据库中当天已抓取文章补入当前运行实例。

    原理：
    1. 先检查“当天 + 主题 + 关键词哈希”是否已经有简报。
    2. 如果没有，说明这批文章还没有真正产出简报，或者简报已被删除。
    3. 此时把数据库里当天已抓取的同主题文章补挂到当前 brief_run 上，再进入 AI。

    这样即使本次爬虫没有抓到新文章，也能基于当天库中已有文章重新生成简报。
    """

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
        logger.info(
            "Brief already exists for date=%s topic=%s keywords_hash=%s, skip backfill.",
            brief_run.run_date,
            brief_run.topic,
            brief_run.keywords_hash,
        )
        return 0

    deleted_brief = (
        db.query(Brief)
        .filter(
            Brief.date == brief_run.run_date,
            Brief.topic == brief_run.topic,
            Brief.keywords_hash == brief_run.keywords_hash,
            Brief.is_deleted == True,
        )
        .order_by(Brief.deleted_at.desc().nullslast(), Brief.id.desc())
        .first()
    )

    candidate_articles: list[Article] = []
    article_map: dict[int, Article] = {}

    if deleted_brief and deleted_brief.article_ids:
        deleted_articles = (
            db.query(Article)
            .filter(
                Article.id.in_(deleted_brief.article_ids),
                Article.content.isnot(None),
                Article.content != "",
            )
            .all()
        )
        for article in deleted_articles:
            article_map[article.id] = article
        logger.info(
            "Loaded %s articles from deleted brief id=%s for topic=%s.",
            len(deleted_articles),
            deleted_brief.id,
            brief_run.topic,
        )

    candidate_query = (
        db.query(Article)
        .filter(
            Article.content.isnot(None),
            Article.content != "",
            Article.source.has(Source.topics == brief_run.topic),
        )
        .order_by(Article.article_date.desc(), Article.published_at.desc().nullslast(), Article.id.desc())
    )
    candidate_rows = candidate_query.all()
    target_article_date = _pick_effective_article_date(candidate_rows)
    scoped_articles = [
        article
        for article in candidate_rows
        if article.article_date == target_article_date
    ] if target_article_date else []
    for article in scoped_articles:
        article_map[article.id] = article

    candidate_articles = list(article_map.values())

    added_count = 0
    for article in candidate_articles:
        article_run = (
            db.query(ArticleRun)
            .filter(
                ArticleRun.brief_run_id == brief_run.id,
                ArticleRun.article_id == article.id,
            )
            .first()
        )
        if article_run:
            continue
        _ensure_article_run(db, brief_run, article)
        added_count += 1

    if added_count:
        logger.info(
            "Backfilled %s existing articles into brief_run=%s for topic=%s using article_date=%s.",
            added_count,
            brief_run.id,
            brief_run.topic,
            target_article_date,
        )
    else:
        logger.info(
            "No existing articles needed backfill for brief_run=%s topic=%s.",
            brief_run.id,
            brief_run.topic,
        )
    db.commit()
    return added_count


@celery_app.task
def crawl_all_sources(
    max_articles: int | None = None,
    process_inline: bool = False,
    topics: list[str] | None = None,
    keywords: list[str] | None = None,
    run_map: dict[str, int] | None = None,
):
    """抓取符合主题的所有数据源。

    这里按 topic 分流，确保不同主题/关键词组合的数据进入各自运行实例。
    """

    db = SessionLocal()
    try:
        selected_topics = _normalize_topics(topics)
        selected_keywords = _normalize_keywords(keywords)
        query = db.query(Source).filter(Source.is_active == True)
        if selected_topics:
            query = query.filter(Source.topics.in_(selected_topics))
        sources = query.all()
        remaining = max_articles if (max_articles is not None and max_articles > 0) else None

        for source in sources:
            if remaining is not None and remaining <= 0:
                break
            logger.info("Crawling source %s", source.name)
            try:
                crawler = get_crawler(source)
                raw_articles = crawler.fetch()
                if not raw_articles:
                    logger.warning("No articles fetched from %s", source.name)
                    continue

                source_topic = (source.topics or "").strip()
                effective_article_date = _pick_effective_article_date(raw_articles)
                if not effective_article_date:
                    logger.info("No articles with parsable dates for %s", source.name)
                    continue
                if effective_article_date != date.today().isoformat():
                    logger.info(
                        "No today articles for %s, fallback to latest available date: %s",
                        source.name,
                        effective_article_date,
                    )
                raw_articles = [
                    item
                    for item in raw_articles
                    if (item.article_date or (item.published_date.isoformat()[:10] if item.published_date else None)) == effective_article_date
                ]
                raw_articles = _filter_new_articles_by_cursor(raw_articles, source, source_topic, selected_keywords)
                if remaining is not None:
                    raw_articles = raw_articles[:remaining]
                if not raw_articles:
                    logger.info("No new articles after Redis cursor filtering for %s", source.name)
                    continue

                payload = [
                    {
                        "url": ra.url,
                        "title": ra.title,
                        "raw_html": ra.raw_html,
                        "published_date": ra.published_date.isoformat() if ra.published_date else None,
                        "article_date": ra.article_date,
                        "image_url": ra.image_url,
                        "source_id": ra.source_id,
                    }
                    for ra in raw_articles
                ]

                target_run_id = None
                if run_map and source_topic in run_map:
                    target_run_id = run_map[source_topic]

                if process_inline:
                    process_raw_articles(payload, brief_run_id=target_run_id)
                else:
                    process_raw_articles.delay(payload, brief_run_id=target_run_id)

                latest_item = max(raw_articles, key=lambda item: item.published_date or datetime.min)
                save_latest_crawl_cursor(
                    source_id=source.id,
                    topic=source_topic,
                    keywords=selected_keywords,
                    latest_title=latest_item.title,
                    latest_published_at=latest_item.published_date,
                    latest_url=latest_item.url,
                )

                logger.info("Processed %s articles from %s", len(raw_articles), source.name)
                if remaining is not None:
                    remaining -= len(raw_articles)
            except Exception as exc:
                logger.error("Error crawling source %s: %s", source.id, exc, exc_info=True)
    finally:
        db.close()


@celery_app.task
def process_raw_articles(raw_articles_data: list, brief_run_id: int | None = None):
    """处理原始文章并建立运行隔离结果。"""

    db = SessionLocal()
    try:
        success_count = 0
        updated_count = 0
        duplicate_count = 0
        error_count = 0
        brief_run = db.query(BriefRun).filter(BriefRun.id == brief_run_id).first() if brief_run_id else None
        effective_article_date = _pick_effective_article_date(raw_articles_data)

        for data in raw_articles_data:
            try:
                url = data["url"]
                raw_html = data["raw_html"]
                clean_content = extract_clean_content(raw_html, url)
                article_date = data.get("article_date") or (data.get("published_date", "")[:10] if data.get("published_date") else None)

                if effective_article_date and article_date != effective_article_date:
                    logger.info("Skip article outside selected date %s before saving: %s", effective_article_date, url)
                    continue
                if not (clean_content or "").strip():
                    logger.warning("Skip article with empty cleaned content: %s", url)
                    continue

                existing_article = db.query(Article).filter(Article.url == url).first()
                if existing_article:
                    old_content = (existing_article.content or "").strip()
                    new_content = clean_content.strip()
                    should_refresh = bool(new_content) and (not old_content or len(new_content) > len(old_content) + 50)
                    if should_refresh:
                        published_at = _parse_iso_datetime(data.get("published_date")) or existing_article.published_at
                        image_no = existing_article.image_no
                        image_path = existing_article.image_path
                        if not image_path:
                            image_no, image_path = _download_and_save_image(
                                url,
                                raw_html,
                                article_date or date.today().isoformat(),
                                data.get("image_url"),
                            )
                        existing_article.title = data["title"]
                        existing_article.content = clean_content
                        existing_article.source_id = data["source_id"]
                        existing_article.image_no = image_no
                        existing_article.image_path = image_path
                        existing_article.published_at = published_at
                        existing_article.article_date = article_date
                        existing_article.summary = None
                        existing_article.tags = None
                        existing_article.topic = None
                        existing_article.quality_score = None
                        existing_article.status = ArticleStatus.pending
                        db.flush()
                        updated_count += 1
                        logger.info("Updated existing article with refreshed content: %s...", data["title"][:50])
                    else:
                        duplicate_count += 1
                        logger.info("Duplicate article skipped (pre-check): %s", url)

                    if brief_run:
                        _ensure_article_run(db, brief_run, existing_article)
                        db.commit()
                    continue

                image_no, image_path = _download_and_save_image(
                    url,
                    raw_html,
                    article_date or date.today().isoformat(),
                    data.get("image_url"),
                )
                article = Article(
                    url=url,
                    title=data["title"],
                    content=clean_content,
                    source_id=data["source_id"],
                    image_no=image_no,
                    image_path=image_path,
                    published_at=_parse_iso_datetime(data.get("published_date")),
                    article_date=article_date,
                )
                db.add(article)
                db.flush()
                if brief_run:
                    _ensure_article_run(db, brief_run, article)
                db.commit()
                success_count += 1
                logger.info("Saved article: %s...", data["title"][:50])
            except IntegrityError:
                db.rollback()
                duplicate_count += 1
                logger.info("Duplicate article skipped (IntegrityError): %s", data.get("url", "unknown"))
            except Exception as exc:
                db.rollback()
                error_count += 1
                logger.error("Error saving article %s: %s", data.get("url", "unknown"), exc, exc_info=True)

        logger.info(
            "Process summary: %s saved, %s updated, %s duplicates, %s errors",
            success_count,
            updated_count,
            duplicate_count,
            error_count,
        )
    finally:
        db.close()


@celery_app.task
def ai_process_articles(brief_run_id: int | None = None):
    """按运行实例执行异步 AI 流程。"""

    db = SessionLocal()
    try:
        llm_router.reset_response_stats()
        if brief_run_id is None:
            brief_run = (
                db.query(BriefRun)
                .filter(BriefRun.run_date == date.today(), BriefRun.status.in_([BriefRunStatus.crawling, BriefRunStatus.pending]))
                .order_by(BriefRun.created_at.desc())
                .first()
            )
        else:
            brief_run = db.query(BriefRun).filter(BriefRun.id == brief_run_id).first()
        if brief_run is None:
            logger.warning("未找到待处理运行实例: %s", brief_run_id)
            return

        brief_run.status = BriefRunStatus.ai_processing
        db.commit()

        article_runs = (
            db.query(ArticleRun)
            .filter(ArticleRun.brief_run_id == brief_run.id, ArticleRun.status == ArticleRunStatus.pending)
            .all()
        )
        for item in article_runs:
            _ = item.article

        passed_runs, dropped_runs = asyncio.run(
            process_article_runs_async(
                article_runs=article_runs,
                topic=brief_run.topic,
                keywords=brief_run.keywords or [],
            )
        )
        db.commit()
        logger.info(
            "AI filter summary: total=%s, kept=%s, dropped=%s, keywords=%s",
            len(article_runs),
            len(passed_runs),
            len(dropped_runs),
            brief_run.keywords or [],
        )
    except Exception as exc:
        db.rollback()
        if isinstance(exc, AllLLMKeysFailedError):
            raise
        logger.error("Error in AI processing: %s", exc, exc_info=True)
        raise
    finally:
        llm_router.log_response_stats()
        db.close()


@celery_app.task
def generate_and_push_brief(run_ids: list[int] | None = None):
    """按运行实例生成并推送简报。"""

    try:
        if not run_ids:
            db = SessionLocal()
            try:
                run_ids = [
                    item.id
                    for item in db.query(BriefRun)
                    .filter(BriefRun.run_date == date.today(), BriefRun.status == BriefRunStatus.ai_processing)
                    .all()
                ]
            finally:
                db.close()
        bindings = load_binding_settings()
        weather_report = None
        if should_fetch_weather(bindings):
            db = SessionLocal()
            try:
                weather_preferences = _load_weather_preferences(db)
            finally:
                db.close()
            region = (weather_preferences.get("region") or settings.DEFAULT_WEATHER_REGION).strip()
            try:
                weather_report = weather_service.get_daily_weather_report(region)
                logger.info("Weather report loaded for region=%s", region)
            except WeatherServiceError as exc:
                logger.warning("Weather report skipped: %s", exc)
            except Exception as exc:
                logger.error("Unexpected weather fetch error: %s", exc, exc_info=True)

        briefs = generate_briefs_for_runs(run_ids or [])
        for brief in briefs:
            if not brief or not brief.html_content:
                continue
            send_email(
                brief_html=brief.html_content,
                brief_date=brief.date,
                brief_title=brief.title,
                weather_report=weather_report,
            )
            brief_url = f"http://localhost:8000/briefs/item/{brief.id}/html"
            send_feishu_robot_card(
                brief_url=brief_url,
                brief_title=brief.title,
                brief_topic=brief.topic,
                brief_date=brief.date,
                weather_report=weather_report,
            )
    except Exception as exc:
        logger.error("Error generating and pushing brief: %s", exc, exc_info=True)


def _create_brief_runs(db, topics: list[str], keywords: list[str] | None) -> dict[str, int]:
    """为本次请求创建运行实例。"""

    run_map: dict[str, int] = {}
    for topic in topics:
        brief_run = BriefRun(
            run_key=_build_run_key(topic, keywords),
            run_date=date.today(),
            topic=topic,
            keywords=_normalize_keywords(keywords),
            keywords_hash=_keywords_hash(topic, keywords),
            status=BriefRunStatus.crawling,
        )
        db.add(brief_run)
        db.flush()
        run_map[topic] = brief_run.id
    db.commit()
    return run_map


@celery_app.task
def run_all_tasks_immediately(topics: list[str] | None = None, keywords: list[str] | None = None):
    """同步执行完整流水线：抓取 -> AI -> 简报。

    设计原则：
    1. 原始文章共享，减少重复抓取。
    2. AI 结果和简报按 BriefRun 隔离，确保多人并发互不覆盖。
    """

    logger.info("开始立即执行全流程流水线...")
    db = SessionLocal()
    run_ids: list[int] = []
    try:
        selected_topics = _normalize_topics(topics) or _load_active_source_topics()
        selected_keywords = _normalize_keywords(keywords)
        logger.info("本次生成主题：%s", ", ".join(selected_topics))
        logger.info("本次生成关键词：%s", ", ".join(selected_keywords) if selected_keywords else "未传入")

        run_map = _create_brief_runs(db, selected_topics, selected_keywords)
        run_ids = list(run_map.values())

        crawl_all_sources(process_inline=True, topics=selected_topics, keywords=selected_keywords, run_map=run_map)
        for run_id in run_ids:
            brief_run = db.query(BriefRun).filter(BriefRun.id == run_id).first()
            if brief_run:
                _backfill_today_articles_for_missing_brief(db, brief_run)
        logger.info("爬虫任务完成，开始 AI 处理...")

        for run_id in run_ids:
            ai_process_articles(brief_run_id=run_id)

        logger.info("AI 处理完成，开始生成简报...")
        generate_and_push_brief(run_ids=run_ids)

        for run_id in run_ids:
            brief_run = db.query(BriefRun).filter(BriefRun.id == run_id).first()
            if brief_run:
                brief_run.status = BriefRunStatus.completed
        db.commit()
        logger.info("✅ 全流程流水线执行完毕！")
        return {"message": "completed", "topics": selected_topics, "keywords": selected_keywords, "run_ids": run_ids}
    except Exception as exc:
        db.rollback()
        for run_id in run_ids:
            run_row = db.query(BriefRun).filter(BriefRun.id == run_id).first()
            if run_row:
                run_row.status = BriefRunStatus.failed
                run_row.error_message = str(exc)
        db.commit()
        if isinstance(exc, AllLLMKeysFailedError):
            logger.error(str(exc))
            return {"message": str(exc), "run_ids": run_ids}
        logger.error("❌ Error in immediate execution pipeline: %s", exc, exc_info=True)
        return {"message": str(exc), "run_ids": run_ids}
    finally:
        db.close()
