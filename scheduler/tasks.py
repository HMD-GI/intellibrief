import logging  # 导入日志模块
import os  # 导入 os，用于文件夹操作
from datetime import date, datetime  # 导入日期和时间工具
from urllib.parse import urlparse  # 导入 URL 解析工具，用于判断图片扩展名

import requests  # 导入 requests，用于下载图片
from sqlalchemy.exc import IntegrityError  # 导入数据库唯一约束异常

from app.config import settings  # 导入项目配置
from app.database import SessionLocal, ensure_sqlite_schema  # 导入数据库会话和 SQLite 结构修复函数
from app.models.article import Article, ArticleStatus  # 导入文章模型
from app.models.source import Source  # 导入数据源模型
from brief.generator import generate_daily_briefs  # 导入简报生成函数
from brief.notifier import send_email, send_webhook  # 导入通知函数
from crawlers import get_crawler  # 导入爬虫工厂
from processor.ai_engine import classify_articles, filter_articles, generate_summaries  # 导入 AI 处理函数
from processor.cleaner import extract_clean_content, extract_first_image_url  # 导入正文清洗和首图提取函数
from processor.dedup import redis_client  # 复用 Redis 客户端生成图片编号
from scheduler.celery_app import celery_app  # 导入 Celery 实例
from utils.llm_router import AllLLMKeysFailedError, llm_router  # 导入大模型路由器和统一异常

logger = logging.getLogger(__name__)  # 初始化日志记录器
ensure_sqlite_schema()  # Worker 单独启动时也保证 SQLite 表结构已修复

PHOTO_ROOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "photo")  # photo 根目录


def _guess_image_ext(image_url: str, content_type: str | None) -> str:  # 猜测图片扩展名
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


def _image_no_exists(day_dir: str, image_no: int) -> bool:  # 判断当天目录中是否已有同编号图片
    prefix = f"{image_no}."
    return any(filename.startswith(prefix) for filename in os.listdir(day_dir))


def _download_and_save_image(article_url: str, raw_html: str, date_str: str, image_url: str | None = None) -> tuple[int | None, str | None]:  # 下载并保存文章图片
    try:
        image_url = image_url or extract_first_image_url(raw_html, article_url)  # 优先使用源专属 XPath 提取到的图片地址
        if not image_url:
            return None, None

        day_dir = os.path.join(PHOTO_ROOT_DIR, date_str)
        os.makedirs(day_dir, exist_ok=True)  # 确保当天图片目录存在

        try:
            image_no = int(redis_client.incr(f"photo_counter:{date_str}"))  # 优先使用 Redis 原子递增
        except Exception:
            existing_files = os.listdir(day_dir)
            existing_numbers = []
            for name in existing_files:
                stem, _ = os.path.splitext(name)
                if stem.isdigit():
                    existing_numbers.append(int(stem))
            image_no = (max(existing_numbers) + 1) if existing_numbers else 1  # Redis 不可用时降级本地计算

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(image_url, headers=headers, timeout=15)
        if resp.status_code != 200 or not resp.content:
            return None, None

        ext = _guess_image_ext(image_url, resp.headers.get("Content-Type"))
        while _image_no_exists(day_dir, image_no):
            image_no += 1  # 防止重复编号覆盖旧文件
        filename = f"{image_no}{ext}"
        file_path = os.path.join(day_dir, filename)
        with open(file_path, "wb") as f:
            f.write(resp.content)

        public_path = f"/photo/{date_str}/{filename}"  # 返回可供前端访问的静态路径
        return image_no, public_path
    except Exception as e:
        logger.error(f"_download_and_save_image failed: {e}", exc_info=True)
        return None, None


def _normalize_topics(topics: list[str] | None) -> list[str]:  # 规范化主题列表
    return [topic.strip() for topic in (topics or []) if topic and topic.strip()]  # 去除空值和首尾空白


def _normalize_keywords(keywords: list[str] | None) -> list[str]:  # 规范化关键词列表
    return [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]  # 去除空值和首尾空白


def _load_active_source_topics() -> list[str]:  # 读取所有激活数据源主题
    db = SessionLocal()
    try:
        return [
            row[0] for row in db.query(Source.topics).filter(Source.is_active == True, Source.topics != "").distinct().all()
        ]  # 每个数据源只有一个 topics，相同主题会自然合并
    finally:
        db.close()


@celery_app.task  # 注册爬取全部数据源任务
def crawl_all_sources(max_articles: int | None = None, process_inline: bool = False, topics: list[str] | None = None):
    db = SessionLocal()
    try:
        selected_topics = _normalize_topics(topics)
        query = db.query(Source).filter(Source.is_active == True)
        if selected_topics:
            query = query.filter(Source.topics.in_(selected_topics))  # 只抓取与所选主题匹配的数据源
        sources = query.all()
        remaining = max_articles if (max_articles is not None and max_articles > 0) else None

        for source in sources:
            if remaining is not None and remaining <= 0:
                break
            logger.info(f"Crawling source {source.name}")
            try:
                crawler = get_crawler(source)
                raw_articles = crawler.fetch()
                if raw_articles:
                    if remaining is not None:
                        raw_articles = raw_articles[:remaining]  # 仅测试场景下才裁切数量

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

                    if process_inline:
                        process_raw_articles(payload)  # 同步入库，方便后续同一流程继续处理
                    else:
                        process_raw_articles.delay(payload)

                    logger.info(f"Processed {len(raw_articles)} articles from {source.name}")
                    if remaining is not None:
                        remaining -= len(raw_articles)
                else:
                    logger.warning(f"No articles fetched from {source.name}")
            except Exception as e:
                logger.error(f"Error crawling source {source.id}: {e}", exc_info=True)
    finally:
        db.close()


@celery_app.task  # 注册原始文章处理任务
def process_raw_articles(raw_articles_data: list):
    """
    处理原始爬虫结果：
    1. 清洗正文并过滤非当天文章；
    2. 保存新文章或刷新旧文章的正文内容；
    3. 只保留真正有正文的文章进入 AI 阶段。
    """
    db = SessionLocal()
    try:
        success_count = 0
        updated_count = 0
        duplicate_count = 0
        error_count = 0

        for data in raw_articles_data:
            try:
                url = data["url"]
                raw_html = data["raw_html"]
                clean_content = extract_clean_content(raw_html, url)  # 提取并清洗正文
                today_str = date.today().isoformat()
                article_date = data.get("article_date") or (
                    data.get("published_date", "")[:10] if data.get("published_date") else None
                )

                if article_date != today_str:
                    logger.info(f"Skip non-today article before saving ({article_date}): {url}")
                    continue
                if not (clean_content or "").strip():
                    logger.warning(f"Skip article with empty cleaned content: {url}")
                    continue

                existing_article = db.query(Article).filter(Article.url == url).first()
                if existing_article:
                    old_content = (existing_article.content or "").strip()
                    new_content = clean_content.strip()
                    should_refresh = bool(new_content) and (
                        not old_content or len(new_content) > len(old_content) + 50
                    )  # 只有正文明显更好时才刷新旧文章
                    if not should_refresh:
                        duplicate_count += 1
                        logger.info(f"Duplicate article skipped (pre-check): {url}")
                        continue

                    image_no = existing_article.image_no
                    image_path = existing_article.image_path
                    if not image_path:
                        image_no, image_path = _download_and_save_image(url, raw_html, today_str, data.get("image_url"))

                    published_at = existing_article.published_at
                    if data.get("published_date"):
                        try:
                            published_at = datetime.fromisoformat(data["published_date"])
                        except Exception:
                            pass

                    existing_article.title = data["title"]
                    existing_article.content = clean_content
                    existing_article.source_id = data["source_id"]
                    existing_article.image_no = image_no
                    existing_article.image_path = image_path
                    existing_article.published_at = published_at
                    existing_article.article_date = article_date
                    existing_article.summary = None  # 重置摘要结果，确保重新进入 AI
                    existing_article.tags = None  # 重置标签
                    existing_article.topic = None  # 重置分类
                    existing_article.quality_score = None  # 重置评分
                    existing_article.status = ArticleStatus.pending  # 重置为待 AI 处理
                    db.commit()
                    updated_count += 1
                    logger.info(f"Updated existing article with refreshed content: {data['title'][:50]}...")
                    continue

                image_no, image_path = _download_and_save_image(url, raw_html, today_str, data.get("image_url"))
                published_at = None
                if data.get("published_date"):
                    try:
                        published_at = datetime.fromisoformat(data["published_date"])
                    except Exception:
                        published_at = None

                article = Article(
                    url=url,
                    title=data["title"],
                    content=clean_content,
                    source_id=data["source_id"],
                    image_no=image_no,
                    image_path=image_path,
                    published_at=published_at,
                    article_date=article_date,
                    status=ArticleStatus.pending,
                )
                db.add(article)
                db.commit()
                success_count += 1
                logger.info(f"Saved article: {data['title'][:50]}...")

            except IntegrityError:
                db.rollback()
                duplicate_count += 1
                logger.info(f"Duplicate article skipped (IntegrityError): {data.get('url', 'unknown')}")
            except Exception as e:
                db.rollback()
                error_count += 1
                logger.error(f"Error saving article {data.get('url', 'unknown')}: {e}")

        logger.info(
            f"Process summary: {success_count} saved, {updated_count} updated, {duplicate_count} duplicates, {error_count} errors"
        )
    except Exception as e:
        logger.error(f"Error processing raw articles: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task  # 注册 AI 处理任务
def ai_process_articles(topics: list[str] | None = None, keywords: list[str] | None = None):
    db = SessionLocal()
    try:
        llm_router.reset_response_stats()  # 每次 AI 任务前清空大模型响应统计
        today_str = date.today().isoformat()  # 只处理当天文章
        selected_topics = _normalize_topics(topics)
        selected_keywords = _normalize_keywords(keywords)

        query = db.query(Article).filter(
            Article.status == ArticleStatus.pending,
            Article.article_date == today_str,
        )
        if selected_topics:
            query = query.filter(Article.source.has(Source.topics.in_(selected_topics)))  # 按数据源主题筛选待处理文章
        articles = query.all()

        filtered_articles = filter_articles(articles, keywords=selected_keywords)  # 第一步筛选时带上关键词数组
        logger.info(
            f"AI filter summary: total={len(articles)}, kept={len(filtered_articles)}, dropped={len(articles) - len(filtered_articles)}, keywords={selected_keywords}"
        )  # 输出筛选结果统计

        for article in articles:
            if article not in filtered_articles:
                article.status = ArticleStatus.filtered  # 未通过第一步筛选则标记为 filtered

        generate_summaries(filtered_articles)  # 第二步生成摘要
        for article in filtered_articles:
            article.status = ArticleStatus.processed  # 摘要完成后标记为已处理

        classify_articles(filtered_articles)  # 第三步执行分类
        db.commit()
    except Exception as e:
        if isinstance(e, AllLLMKeysFailedError):
            logger.error(str(e))
            db.rollback()
            raise
        logger.error(f"Error in AI processing: {e}")
        db.rollback()
    finally:
        llm_router.log_response_stats()  # 输出本轮模型成功/失败统计
        db.close()


@celery_app.task  # 注册生成并推送简报任务
def generate_and_push_brief(topics: list[str] | None = None):
    try:
        today = date.today()
        selected_topics = _normalize_topics(topics)
        if not selected_topics:
            selected_topics = _load_active_source_topics()  # 未指定主题时，按全部激活数据源主题生成

        briefs = generate_daily_briefs(today, selected_topics)
        for brief in briefs:
            if not brief or not brief.html_content:
                continue
            send_email(brief.html_content, today)  # 邮件推送
            brief_url = f"http://localhost:8000/briefs/item/{brief.id}/html"
            send_webhook(brief_url)  # 飞书推送
    except Exception as e:
        logger.error(f"Error generating and pushing brief: {e}")


@celery_app.task  # 注册立即执行完整流水线任务
def run_all_tasks_immediately(topics: list[str] | None = None, keywords: list[str] | None = None):
    """
    一键触发完整的流水线：爬虫 -> AI 处理 -> 生成简报。
    该任务主要用于前端一键生成和测试场景，采用同步调用保证顺序执行。
    """
    logger.info("开始立即执行全流程流水线...")
    try:
        selected_topics = _normalize_topics(topics)
        selected_keywords = _normalize_keywords(keywords)
        if not selected_topics:
            selected_topics = _load_active_source_topics()

        logger.info(f"本次生成主题：{', '.join(selected_topics)}")
        logger.info(f"本次生成关键词：{', '.join(selected_keywords) if selected_keywords else '未传入'}")  # 输出本次关键词

        crawl_all_sources(process_inline=True, topics=selected_topics)  # 第一步：先抓取并同步入库
        logger.info("爬虫任务完成，开始 AI 处理...")

        ai_process_articles(topics=selected_topics, keywords=selected_keywords)  # 第二步：第一步筛选时带关键词组合
        logger.info("AI 处理完成，开始生成简报...")

        generate_and_push_brief(topics=selected_topics)  # 第三步：按主题生成对应简报
        logger.info("✅ 全流程流水线执行完毕！")
        return {"message": "completed", "topics": selected_topics, "keywords": selected_keywords}
    except Exception as e:
        if isinstance(e, AllLLMKeysFailedError):
            logger.error(str(e))
            return {"message": str(e)}
        logger.error(f"❌ Error in immediate execution pipeline: {e}", exc_info=True)
        return {"message": str(e)}
