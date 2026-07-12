import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # 使用前先探活，避免拿到失效连接
    pool_size=20,  # 提高连接池容量，支撑多人并发
    max_overflow=40,  # 高峰时允许额外连接
    pool_recycle=1800,  # 定期回收连接，降低长连接失效风险
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # 提交后不自动失效，降低并发场景下二次懒加载问题
    bind=engine,
)

Base = declarative_base()


def ensure_sqlite_schema():
    """兼容旧调用。

    当前数据库已经切到 PostgreSQL，这里不再执行 SQLite 结构修复。
    """

    logger.info("ensure_sqlite_schema skipped: current database is %s", settings.DATABASE_URL)


def ensure_postgres_schema_updates():
    """启动时补齐 PostgreSQL 历史缺失列。

    技术说明：
    1. 目前项目未接入 Alembic。
    2. 为避免历史库直接升级时报字段缺失错误，启动时做最小 DDL 自修复。
    3. 本次只补简报软删除相关字段，范围可控。
    """

    if not settings.DATABASE_URL.startswith("postgresql"):
        return

    ddl_list = [
        "ALTER TABLE briefs ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE briefs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
    ]
    with engine.begin() as conn:
        for ddl in ddl_list:
            conn.execute(text(ddl))


def get_db():
    """FastAPI 依赖：按请求创建独立数据库会话。"""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
