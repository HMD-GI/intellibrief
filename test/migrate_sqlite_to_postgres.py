import json
import os
import sqlite3
import sys
from datetime import datetime

import psycopg2
from psycopg2.extras import Json
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: F401  # 导入全部模型，确保目标库建表时元数据完整
from app.database import Base


SQLITE_PATH = "intellibrief.db"
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = "123456"
PG_DBNAME = "intellibrief_pg"


def _normalize_json_value(value):
    """兼容 SQLite 中的 JSON 文本。"""

    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _normalize_datetime(value):
    """兼容 SQLite 时间字段。"""

    if value in (None, ""):
        return None
    text = str(value).replace("T", " ")
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def create_database_if_needed():
    """如果 PostgreSQL 数据库不存在则创建。"""

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname="postgres",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DBNAME,))
    exists = cur.fetchone() is not None
    if not exists:
        cur.execute(f'CREATE DATABASE "{PG_DBNAME}"')
        print(f"created database: {PG_DBNAME}")
    else:
        print(f"database exists: {PG_DBNAME}")
    cur.close()
    conn.close()


def _reset_sequence(pg_cur, table: str):
    """重置 PostgreSQL 自增序列。"""

    allowed_tables = {
        "sources",
        "articles",
        "brief_runs",
        "article_runs",
        "briefs",
        "app_settings",
    }
    if table not in allowed_tables:
        raise ValueError(f"unsupported table: {table}")
    pg_cur.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 1),
            true
        )
        """
    )


def migrate():
    """执行 SQLite -> PostgreSQL 数据迁移。"""

    # 先确保 PostgreSQL 新库表结构存在，再执行数据迁移。
    pg_engine = create_engine(
        f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DBNAME}"
    )
    Base.metadata.create_all(bind=pg_engine)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DBNAME,
    )
    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    try:
        for table in ["article_runs", "brief_runs", "briefs", "articles", "sources", "app_settings"]:
            pg_cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')

        sqlite_cur.execute("SELECT * FROM sources ORDER BY id")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                """
                INSERT INTO sources (id, name, source_type, url, parser_config, topics, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["id"],
                    row["name"],
                    row["source_type"],
                    row["url"],
                    Json(_normalize_json_value(row["parser_config"])),
                    row["topics"],
                    bool(row["is_active"]),
                ),
            )

        sqlite_cur.execute("SELECT * FROM articles ORDER BY id")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                """
                INSERT INTO articles (
                    id, url, title, content, summary, tags, topic, image_no, image_path,
                    source_id, published_at, article_date, fetched_at, quality_score, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["id"],
                    row["url"],
                    row["title"],
                    row["content"],
                    row["summary"],
                    row["tags"],
                    row["topic"],
                    row["image_no"],
                    row["image_path"],
                    row["source_id"],
                    _normalize_datetime(row["published_at"]),
                    row["article_date"],
                    _normalize_datetime(row["fetched_at"]),
                    row["quality_score"],
                    row["status"],
                ),
            )

        sqlite_cur.execute("SELECT * FROM briefs ORDER BY id")
        brief_columns = {desc[0] for desc in sqlite_cur.description}
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                """
                INSERT INTO briefs (
                    id, date, title, topic, brief_type, html_content, article_ids,
                    keywords, keywords_hash, run_key, brief_run_id, is_deleted, deleted_at, generated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["id"],
                    row["date"],
                    row["title"],
                    row["topic"],
                    row["brief_type"],
                    row["html_content"],
                    Json(_normalize_json_value(row["article_ids"])),
                    Json(_normalize_json_value(row["keywords"])) if "keywords" in brief_columns else Json([]),
                    row["keywords_hash"] if "keywords_hash" in brief_columns else None,
                    row["run_key"] if "run_key" in brief_columns else None,
                    row["brief_run_id"] if "brief_run_id" in brief_columns else None,
                    bool(row["is_deleted"]) if "is_deleted" in brief_columns and row["is_deleted"] is not None else False,
                    _normalize_datetime(row["deleted_at"]) if "deleted_at" in brief_columns else None,
                    _normalize_datetime(row["generated_at"]),
                ),
            )

        sqlite_cur.execute("SELECT * FROM app_settings ORDER BY id")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                """
                INSERT INTO app_settings (id, key, value, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    row["id"],
                    row["key"],
                    row["value"],
                    _normalize_datetime(row["updated_at"]),
                ),
            )

        for table in ["sources", "articles", "briefs", "app_settings"]:
            _reset_sequence(pg_cur, table)

        pg_conn.commit()
        print("migration completed")
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_cur.close()
        pg_conn.close()
        sqlite_cur.close()
        sqlite_conn.close()


if __name__ == "__main__":
    create_database_if_needed()
    migrate()
