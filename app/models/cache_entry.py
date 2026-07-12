import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class CacheEntry(Base):
    """通用缓存表。

    技术说明：
    1. 该表用于承接原本只放在 Redis 中的业务缓存数据。
    2. Redis 继续作为热缓存使用，PostgreSQL 负责持久化和兜底查询。
    3. value_type 用于标记当前 value 的数据结构，便于统一做字符串 / JSON / 集合 / 列表操作。
    """

    __tablename__ = "cache_entries"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    value_type = Column(String(32), nullable=False, default="string")
    expires_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )
