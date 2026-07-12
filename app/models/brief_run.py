import datetime
import enum

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class BriefRunStatus(str, enum.Enum):
    """简报运行状态。"""

    pending = "pending"
    crawling = "crawling"
    ai_processing = "ai_processing"
    generating = "generating"
    completed = "completed"
    failed = "failed"


class BriefRun(Base):
    """一次独立的简报运行实例。

    用于保证多人并发时的数据隔离。
    同一天、同主题、不同关键词，都会拥有独立 run_key 和独立结果集。
    """

    __tablename__ = "brief_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_key = Column(String, unique=True, index=True, nullable=False)
    run_date = Column(Date, index=True, nullable=False)
    topic = Column(String, index=True, nullable=False)
    keywords = Column(JSON, nullable=True)
    keywords_hash = Column(String, index=True, nullable=False)
    status = Column(Enum(BriefRunStatus), default=BriefRunStatus.pending, index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        index=True,
    )

    article_runs = relationship("ArticleRun", back_populates="brief_run", cascade="all, delete-orphan")
    briefs = relationship("Brief", back_populates="brief_run")

    __table_args__ = (
        Index("ix_brief_runs_date_topic_hash", "run_date", "topic", "keywords_hash"),
    )


class ArticleRunStatus(str, enum.Enum):
    """单篇文章在某次运行中的处理状态。"""

    pending = "pending"
    filtered = "filtered"
    processed = "processed"
    failed = "failed"


class ArticleRun(Base):
    """文章在某次简报运行中的独立结果。"""

    __tablename__ = "article_runs"

    id = Column(Integer, primary_key=True, index=True)
    brief_run_id = Column(Integer, ForeignKey("brief_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    source_topic = Column(String, index=True, nullable=True)
    score = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    tags = Column(String, nullable=True)
    classified_topic = Column(String, nullable=True)
    status = Column(Enum(ArticleRunStatus), default=ArticleRunStatus.pending, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        index=True,
    )

    brief_run = relationship("BriefRun", back_populates="article_runs")
    article = relationship("Article", back_populates="runs")

    __table_args__ = (
        Index("ix_article_runs_run_article", "brief_run_id", "article_id", unique=True),
    )
