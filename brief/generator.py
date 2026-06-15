import logging  # 导入日志
import json  # 导入 JSON
from datetime import date  # 导入 date
from collections import defaultdict  # 导入带默认值的字典
import os  # 导入 os，用于读取本地图片文件
from jinja2 import Environment, FileSystemLoader  # 导入 Jinja2 模板引擎
from app.database import SessionLocal  # 导入数据库会话工厂
from app.models.article import Article, ArticleStatus  # 导入文章模型
from app.models.brief import Brief  # 导入简报模型

logger = logging.getLogger(__name__)  # 初始化日志
DIGEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest")  # 简报文件输出目录

def load_json_filter(value):  # 自定义 Jinja2 过滤器：将字符串解析为 JSON
    try:
        return json.loads(value)  # 尝试解析
    except:
        return {}  # 失败则返回空字典

# 初始化 Jinja2 环境，加载 app/templates 目录下的模板
env = Environment(loader=FileSystemLoader('app/templates'))
env.filters['load_json'] = load_json_filter  # 注册自定义的 load_json 过滤器

def _group_articles_by_topic(articles: list[Article]) -> dict:  # 将文章按 topic 分组
    grouped_articles = defaultdict(list)  # 初始化分组字典
    for article in articles:
        grouped_articles[article.topic or "其他"].append(article)
    return grouped_articles

def _build_image_map(date_str: str) -> dict[int, str]:  # 根据 photo/<日期>/ 目录构建图片编号映射
    """
    从 photo/<日期>/ 目录读取图片文件名（例如 1.jpg、2.png），构建 {编号: /photo/<日期>/<文件名>} 的映射。
    这样简报展示时可以“按编号”准确匹配文章图片。
    """
    photo_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "photo")  # photo 根目录
    day_dir = os.path.join(photo_root, date_str)  # 当天目录
    if not os.path.isdir(day_dir):
        return {}

    image_map: dict[int, str] = {}
    for filename in os.listdir(day_dir):
        stem, _ = os.path.splitext(filename)
        if not stem.isdigit():
            continue
        image_map[int(stem)] = f"/photo/{date_str}/{filename}"
    return image_map

def _save_digest_file(brief_date: date, html_content: str) -> str:  # 将生成的简报 HTML 保存到 digest 目录
    os.makedirs(DIGEST_DIR, exist_ok=True)  # 确保 digest 目录存在
    file_path = os.path.join(DIGEST_DIR, f"brief_{brief_date.strftime('%Y-%m-%d')}.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def generate_daily_brief(brief_date: date) -> Brief:  # 定义生成每日简报函数
    db = SessionLocal()  # 获取数据库会话
    try:
        # 检查是否已生成当天的简报
        existing_brief = db.query(Brief).filter(Brief.date == brief_date).first()
        if existing_brief:
            logger.info(f"Brief for {brief_date} already exists.")  # 记录已存在日志
            if existing_brief.html_content:
                _save_digest_file(brief_date, existing_brief.html_content)  # 已存在记录也同步落盘到 digest
            return existing_brief  # 直接返回现有简报
            
        # 查询当天处理完成且分数及格 (>=60) 的高质量文章
        articles = db.query(Article).filter(
            Article.status == ArticleStatus.processed,
            Article.quality_score >= 60,
            Article.article_date == brief_date.strftime("%Y-%m-%d")
        ).all()
        
        if not articles:  # 如果没有满足条件的文章
            logger.info("No articles to generate brief.")  # 记录日志
            return None  # 返回空
            
        article_ids = []  # 初始化文章 ID 列表
        for article in articles:  # 遍历文章
            article_ids.append(article.id)  # 记录 ID
        grouped_articles = _group_articles_by_topic(articles)  # 按主题分组
        date_str = brief_date.strftime("%Y-%m-%d")  # 获取日期字符串
        image_map = _build_image_map(date_str)  # 构建图片编号映射
            
        # 使用 Jinja2 渲染 HTML 模板
        template = env.get_template('brief.html')  # 加载 brief.html 模板
        html_content = template.render(  # 传入数据渲染模板
            date=brief_date.strftime("%Y-%m-%d"),  # 兼容旧变量
            date_label=brief_date.strftime("%Y-%m-%d"),  # 新变量：日期展示
            report_title="IntelliBrief 每日简报",  # 报告标题
            subtitle="测试模式：每次只抓取少量文章并支持配图展示",  # 子标题
            grouped_articles=grouped_articles,  # 传入分组后的文章
            image_map=image_map,  # 传入图片编号映射（按编号匹配文章图片）
            total_count=len(articles)  # 传入总文章数
        )
        
        brief = Brief(  # 构建简报 ORM 实例
            date=brief_date,  # 设置日期
            title=f"IntelliBrief 每日简报 - {brief_date.strftime('%Y-%m-%d')}",  # 设置标题
            html_content=html_content,  # 存入渲染后的 HTML
            article_ids=article_ids  # 存入关联的文章 ID
        )
        db.add(brief)  # 添加到会话
        db.commit()  # 提交事务
        db.refresh(brief)  # 刷新获取对象 ID
        _save_digest_file(brief_date, html_content)  # 将简报 HTML 文件保存到 digest 目录
        return brief  # 返回简报对象
    except Exception as e:
        logger.error(f"Error generating brief: {e}")  # 记录异常
        db.rollback()  # 异常回滚
        return None
    finally:
        db.close()  # 关闭会话
