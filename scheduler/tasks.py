import logging  # 导入日志
from datetime import date, datetime  # 导入 date/datetime
from sqlalchemy.exc import IntegrityError  # 导入 IntegrityError 处理唯一约束冲突
import os  # 导入 os，用于文件夹操作
import requests  # 导入 requests，用于下载图片
from scheduler.celery_app import celery_app  # 导入 celery 实例
from app.database import SessionLocal, ensure_sqlite_schema  # 导入会话工厂和 SQLite 表结构自修复函数
from app.config import settings  # 导入配置（用于 Redis、路径等）
from app.models.source import Source  # 导入 Source 模型
from app.models.article import Article, ArticleStatus  # 导入 Article 模型
from crawlers import get_crawler  # 导入爬虫工厂函数
from processor.cleaner import extract_clean_content, extract_first_image_url  # 导入清洗函数、图片提取函数
from processor.ai_engine import classify_articles, filter_articles, generate_summary  # 导入 AI 处理函数
from utils.llm_router import AllLLMKeysFailedError, llm_router  # 导入大模型路由实例，用于输出响应统计
from brief.generator import generate_daily_brief  # 导入简报生成函数
from brief.notifier import send_email, send_webhook  # 导入推送函数
from processor.dedup import redis_client  # 复用 dedup 模块里的 Redis 客户端（用于图片编号自增）
from urllib.parse import urlparse  # 导入 urlparse，用于解析图片扩展名

logger = logging.getLogger(__name__)  # 初始化日志
ensure_sqlite_schema()  # Celery worker 单独启动时也确保 articles 表包含新增字段

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

def _image_no_exists(day_dir: str, image_no: int) -> bool:  # 判断当天目录中是否已有相同编号的图片
    prefix = f"{image_no}."
    return any(filename.startswith(prefix) for filename in os.listdir(day_dir))

def _download_and_save_image(article_url: str, raw_html: str, date_str: str, image_url: str | None = None) -> tuple[int | None, str | None]:  # 下载并保存文章图片
    """
    如果文章包含图片，则抓取第一张图片并保存到 photo/<date_str>/ 目录下。
    图片文件名使用编号（1、2、3...），用于周报展示。
    """
    try:
        image_url = image_url or extract_first_image_url(raw_html, article_url)  # 优先使用源专属 XPath 提取到的图片 URL
        if not image_url:
            return None, None

        day_dir = os.path.join(PHOTO_ROOT_DIR, date_str)  # 当天图片目录
        os.makedirs(day_dir, exist_ok=True)  # 创建当天目录

        # 使用 Redis 原子自增生成图片编号；如果 Redis 不可用，则退化为本地文件数计数（测试场景更稳）
        try:
            image_no = int(redis_client.incr(f"photo_counter:{date_str}"))  # 使用 Redis 原子自增生成图片编号
        except Exception:
            existing_files = os.listdir(day_dir)  # 获取已存在的文件
            existing_numbers = []
            for name in existing_files:
                stem, _ = os.path.splitext(name)
                if stem.isdigit():
                    existing_numbers.append(int(stem))
            image_no = (max(existing_numbers) + 1) if existing_numbers else 1
        headers = {"User-Agent": "Mozilla/5.0"}  # 伪装浏览器
        resp = requests.get(image_url, headers=headers, timeout=15)  # 下载图片
        if resp.status_code != 200 or not resp.content:
            return None, None


        ext = _guess_image_ext(image_url, resp.headers.get("Content-Type"))  # 猜测扩展名
        while _image_no_exists(day_dir, image_no):
            image_no += 1  # 防止重复运行或 Redis 计数丢失时覆盖已有图片
        filename = f"{image_no}{ext}"  # 生成文件名（编号+扩展名）
        file_path = os.path.join(day_dir, filename)  # 生成保存路径
        with open(file_path, "wb") as f:
            f.write(resp.content)  # 保存图片二进制内容

        public_path = f"/photo/{date_str}/{filename}"  # FastAPI 静态路径
        return image_no, public_path
    except Exception as e:
        logger.error(f"_download_and_save_image failed: {e}", exc_info=True)
        return None, None

@celery_app.task  # 注册为 Celery 任务
def crawl_all_sources(max_articles: int | None = None, process_inline: bool = False):  # 定义抓取所有源的任务
    db = SessionLocal()  # 获取数据库会话
    try:
        sources = db.query(Source).filter(Source.is_active == True).all()  # 查询所有激活的信息源
        remaining = max_articles if (max_articles is not None and max_articles > 0) else None  # 剩余可抓取数量
        for source in sources:  # 遍历信息源
            if remaining is not None and remaining <= 0:
                break
            logger.info(f"Crawling source {source.name}")  # 记录日志
            try:
                crawler = get_crawler(source)  # 获取对应的爬虫实例
                raw_articles = crawler.fetch()  # 执行抓取
                
                if raw_articles:  # 如果抓取到文章
                    if remaining is not None:
                        raw_articles = raw_articles[:remaining]  # 测试模式：在当天文章结果内继续限制数量

                    payload = [
                        {
                            "url": ra.url,
                            "title": ra.title,
                            "raw_html": ra.raw_html,
                            "published_date": ra.published_date.isoformat() if ra.published_date else None,
                            "article_date": ra.article_date,
                            "image_url": ra.image_url,
                            "source_id": ra.source_id
                        } for ra in raw_articles
                    ]

                    if process_inline:  # 测试模式：同步处理，确保后续 AI/周报可立即看到结果
                        process_raw_articles(payload)
                    else:  # 正常模式：异步派发给 Celery worker
                        process_raw_articles.delay(payload)

                    logger.info(f"Processed {len(raw_articles)} articles from {source.name}")
                    if remaining is not None:
                        remaining -= len(raw_articles)
                else:
                    logger.warning(f"No articles fetched from {source.name}")
            except Exception as e:
                logger.error(f"Error crawling source {source.id}: {e}", exc_info=True)  # 记录抓取异常
    finally:
        db.close()  # 关闭会话


@celery_app.task  # 注册为 Celery 任务
def process_raw_articles(raw_articles_data: list):  # 定义处理原始文章的任务
    """
    处理原始文章：直接插入数据库，依赖 UNIQUE 约束捕获重复。
    不依赖前置检查（check-then-insert），避免 SQLAlchemy session failed state 导致 query 不可信。
    """
    db = SessionLocal()  # 获取会话
    try:
        success_count = 0
        duplicate_count = 0
        error_count = 0

        for data in raw_articles_data:  # 遍历原始文章数据
            try:
                url = data['url']  # 提取 URL
                raw_html = data['raw_html']  # 提取 HTML

                # 先做一次轻量级存在性检查，避免重复 URL 反复下载图片、浪费测试资源
                if db.query(Article.id).filter(Article.url == url).first():
                    duplicate_count += 1
                    logger.info(f"Duplicate article skipped (pre-check): {url}")
                    continue

                clean_content = extract_clean_content(raw_html, url)  # 提取并清洗正文
                today_str = date.today().isoformat()  # 获取当天日期字符串
                article_date = data.get("article_date") or (
                    data.get("published_date", "")[:10] if data.get("published_date") else None
                )  # 优先使用爬虫解析出的 YYYY-MM-DD 日期
                if article_date != today_str:
                    logger.info(f"Skip non-today article before saving ({article_date}): {url}")
                    continue

                image_no, image_path = _download_and_save_image(url, raw_html, today_str, data.get("image_url"))  # 下载并保存图片（如果有）
                published_at = None
                if data.get("published_date"):
                    try:
                        published_at = datetime.fromisoformat(data["published_date"])  # 解析 ISO 格式发布时间
                    except Exception:
                        published_at = None

                # 直接插入，让数据库 UNIQUE 约束做最终去重裁判
                # 不依赖先查后插，避免 session failed state 导致 query 不可信
                article = Article(  # 构造文章实体
                    url=url,
                    title=data['title'],
                    content=clean_content,
                    source_id=data['source_id'],
                    image_no=image_no,  # 保存图片编号
                    image_path=image_path,  # 保存图片访问路径
                    published_at=published_at,  # 保存文章详情页发布时间
                    article_date=article_date,  # 保存 YYYY-MM-DD 格式文章日期
                    status=ArticleStatus.pending  # 状态设为待处理
                )
                db.add(article)  # 存入数据库
                db.commit()  # 立即提交单篇文章
                success_count += 1
                logger.info(f"✅ Saved article: {data['title'][:50]}...")

            except IntegrityError:  # 数据库唯一约束冲突 => 重复文章
                db.rollback()  # 必须 rollback 恢复 session 状态
                duplicate_count += 1
                logger.info(f"Duplicate article skipped (IntegrityError): {url}")

            except Exception as e:
                db.rollback()  # 必须 rollback，否则 session 进入 failed state
                error_count += 1
                logger.error(f"❌ Error saving article {data.get('url', 'unknown')}: {e}")
                # 继续处理下一篇文章，不中断整个流程

        logger.info(f"📊 Process summary: {success_count} saved, {duplicate_count} duplicates, {error_count} errors")

    except Exception as e:
        logger.error(f"Error processing raw articles: {e}")  # 记录异常
        db.rollback()  # 发生异常时回滚
    finally:
        db.close()  # 关闭会话

@celery_app.task  # 注册为 Celery 任务
def ai_process_articles():  # 定义 AI 处理任务
    db = SessionLocal()  # 获取会话
    try:
        llm_router.reset_response_stats()  # 每次 AI 任务开始前清空大模型响应统计
        today_str = date.today().isoformat()  # 只处理当天文章，避免旧文章进入大模型流程
        # 获取当天状态为 pending 的全部文章，确保当天抓取结果都会进入大模型流程
        articles = db.query(Article).filter(
            Article.status == ArticleStatus.pending,
            Article.article_date == today_str
        ).all()
        
        # 1. 使用 GLM 完成快速打分筛选
        filtered_articles = filter_articles(articles)
        for article in articles:  # 遍历处理
            if article not in filtered_articles:  # 如果未通过筛选
                article.status = ArticleStatus.filtered # 标记为已过滤（不会进入简报）
            else:
                # 2. 摘要：使用 DeepSeek 生成深度摘要（不等待）
                generate_summary(article)
                article.status = ArticleStatus.processed  # 标记为已处理完成

        # 3. 使用 GLM 对筛选通过的文章进行主题分类
        classify_articles(filtered_articles)

        db.commit()  # 提交事务
    except Exception as e:
        if isinstance(e, AllLLMKeysFailedError):
            logger.error(str(e))  # 所有 API Key 均失败时直接结束当前 AI 流程
            db.rollback()
            raise
        logger.error(f"Error in AI processing: {e}")  # 记录异常
        db.rollback()  # 回滚
    finally:
        llm_router.log_response_stats()  # AI 处理结束后输出大模型最终成功/失败统计
        db.close()  # 关闭会话

@celery_app.task  # 注册为 Celery 任务
def generate_and_push_brief():  # 定义生成与推送简报的任务
    try:
        today = date.today()  # 获取当天日期
        brief = generate_daily_brief(today)  # 调用生成逻辑生成简报
        
        if brief and brief.html_content:  # 如果成功生成了简报 HTML
            # 通过邮件推送
            send_email(brief.html_content, today)
            
            # 通过 Webhook 推送 (例如飞书)
            brief_url = f"http://localhost:8000/briefs/{today.isoformat()}"  # 构造在线访问链接
            send_webhook(brief_url)  # 发送卡片消息
    except Exception as e:
        logger.error(f"Error generating and pushing brief: {e}")  # 记录异常

@celery_app.task  # 注册为 Celery 任务
def run_all_tasks_immediately():  # 定义一个立即执行整个流水线的任务
    """
    一键触发完整的流水线：爬虫 -> AI 处理 -> 生成简报
    此任务主要用于测试和手动触发，避免等待定时任务。
    注意：现在使用同步调用确保每个步骤完成后才执行下一步。
    """
    logger.info("开始立即执行全流程流水线...")
    try:
        # 1. 执行全量爬取（同步处理当天所有文章）
        crawl_all_sources(process_inline=True)
        
        logger.info("爬虫任务完成，开始 AI 处理...")
        # 2. AI 处理（处理所有 status 为 pending 的文章）
        ai_process_articles()
        
        logger.info("AI 处理完成，开始生成简报...")
        # 3. 生成简报并推送
        generate_and_push_brief()
        
        logger.info("✅ 全流程流水线执行完毕！")
    except Exception as e:
        if isinstance(e, AllLLMKeysFailedError):
            logger.error(str(e))  # 大模型整体不可用时停止后续简报生成
            return {"message": str(e)}
        logger.error(f"❌ Error in immediate execution pipeline: {e}", exc_info=True)
