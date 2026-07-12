import datetime
import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ArticleStatus(str, enum.Enum):
    """文章原始抓取状态。"""

    pending = "pending"  # 新抓取或待处理
    filtered = "filtered"  # 被筛掉
    processed = "processed"  # 已完成处理


class Article(Base):
    """原始文章表。

    该表只保存“共享的原始抓取数据”。
    与某次简报运行强绑定的 AI 结果，统一放到 article_runs 表中，避免多人并发时互相覆盖。
    """

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)

    # 下面这些字段保留为兼容历史逻辑使用，但新的简报生成不再依赖它们做隔离。
    summary = Column(Text, nullable=True)
    tags = Column(String, nullable=True)
    topic = Column(String, nullable=True)
    quality_score = Column(Float, nullable=True)
    status = Column(Enum(ArticleStatus), default=ArticleStatus.pending, index=True)

    image_no = Column(Integer, nullable=True)
    image_path = Column(String, nullable=True)

    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True, index=True)
    source = relationship("Source")

    published_at = Column(DateTime, nullable=True, index=True)
    article_date = Column(String, index=True, nullable=True)
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    runs = relationship("ArticleRun", back_populates="article", cascade="all, delete-orphan")
