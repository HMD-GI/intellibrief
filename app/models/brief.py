import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Brief(Base):
    """简报结果表。"""

    __tablename__ = "briefs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, index=True, nullable=False)
    title = Column(String, nullable=False)
    topic = Column(String, index=True, nullable=True)
    brief_type = Column(String, index=True, nullable=True)
    html_content = Column(Text, nullable=False)
    article_ids = Column(JSON, nullable=True)
    keywords = Column(JSON, nullable=True)
    keywords_hash = Column(String, index=True, nullable=True)
    run_key = Column(String, index=True, nullable=True)
    brief_run_id = Column(Integer, ForeignKey("brief_runs.id"), nullable=True, index=True)
    is_deleted = Column(Boolean, default=False, index=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)
    generated_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    brief_run = relationship("BriefRun", back_populates="briefs")
