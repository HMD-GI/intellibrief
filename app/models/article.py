from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, Enum  # 导入 SQLAlchemy 列类型
from sqlalchemy.orm import relationship  # 导入 relationship 用于定义外键关联
import enum  # 导入 enum 模块
import datetime  # 导入 datetime 模块
from app.database import Base  # 导入 ORM 基类

class ArticleStatus(str, enum.Enum):  # 定义文章处理状态的枚举类
    pending = "pending"  # 待处理状态（刚爬取完毕）
    filtered = "filtered"  # 已过滤状态（经大模型打分后）
    processed = "processed"  # 已处理状态（生成摘要、打标签后）

class Article(Base):  # 定义 Article 数据模型
    __tablename__ = "articles"  # 指定表名为 articles

    id = Column(Integer, primary_key=True, index=True)  # 定义主键 ID，整型并建立索引
    url = Column(String, unique=True, index=True)  # 定义文章 URL 列，要求唯一并建立索引
    title = Column(String)  # 定义文章标题列，字符串类型
    content = Column(Text, nullable=True)  # 定义文章正文列，长文本类型，允许为空
    summary = Column(Text, nullable=True)  # 定义文章摘要列，长文本类型，允许为空（存储 JSON 字符串）
    tags = Column(String, nullable=True) # 定义文章标签列，逗号分隔的字符串，允许为空
    topic = Column(String, nullable=True)  # 定义文章主题分类列，允许为空
    image_no = Column(Integer, nullable=True)  # 定义文章配图编号（用于周报展示），允许为空
    image_path = Column(String, nullable=True)  # 定义文章配图本地访问路径（例如 /photo/2026-06-10/1.jpg），允许为空
    
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)  # 定义来源外键，关联 sources 表的 id
    source = relationship("Source")  # 定义 ORM 关系，方便通过 article.source 访问 Source 对象
    
    published_at = Column(DateTime, nullable=True)  # 定义文章发布时间，允许为空
    article_date = Column(String, index=True, nullable=True)  # 存储文章日期字符串，格式为 YYYY-MM-DD，便于按天筛选
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)  # 定义文章抓取时间，默认为当前 UTC 时间
    quality_score = Column(Float, nullable=True)  # 定义文章质量得分（大模型评分），浮点型，允许为空
    
    status = Column(Enum(ArticleStatus), default=ArticleStatus.pending)  # 定义文章状态列，默认值为 pending
