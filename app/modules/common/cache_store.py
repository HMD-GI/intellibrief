import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.cache_entry import CacheEntry

logger = logging.getLogger(__name__)


def _calc_expires_at(ttl_seconds: int | None) -> datetime | None:
    """根据 TTL 计算过期时间。"""

    if not ttl_seconds or ttl_seconds <= 0:
        return None
    return datetime.utcnow() + timedelta(seconds=ttl_seconds)


def _load_valid_entry(db: Session, key: str) -> CacheEntry | None:
    """读取未过期缓存项，过期则顺手清理。"""

    row = db.query(CacheEntry).filter(CacheEntry.key == key).first()
    if row and row.expires_at and row.expires_at <= datetime.utcnow():
        db.delete(row)
        db.commit()
        return None
    return row


def load_text_cache(key: str) -> str | None:
    """从 PostgreSQL 读取字符串缓存。"""

    db = SessionLocal()
    try:
        row = _load_valid_entry(db, key)
        return row.value if row else None
    finally:
        db.close()


def save_text_cache(key: str, value: str, *, ttl_seconds: int | None = None, value_type: str = "string") -> None:
    """将字符串缓存写入 PostgreSQL。"""

    db = SessionLocal()
    try:
        row = db.query(CacheEntry).filter(CacheEntry.key == key).first()
        if row is None:
            row = CacheEntry(key=key)
            db.add(row)
        row.value = value
        row.value_type = value_type
        row.expires_at = _calc_expires_at(ttl_seconds)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("PostgreSQL cache write failed: key=%s error=%s", key, exc)
    finally:
        db.close()


def load_json_cache(key: str, default=None):
    """从 PostgreSQL 读取 JSON 缓存。"""

    raw = load_text_cache(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def save_json_cache(key: str, value, *, ttl_seconds: int | None = None, value_type: str = "json") -> None:
    """将 JSON 缓存写入 PostgreSQL。"""

    save_text_cache(
        key,
        json.dumps(value, ensure_ascii=False),
        ttl_seconds=ttl_seconds,
        value_type=value_type,
    )


def cache_set_contains(key: str, member: str) -> bool:
    """检查 PostgreSQL 中的集合缓存是否包含指定成员。"""

    values = load_json_cache(key, default=[])
    if not isinstance(values, list):
        return False
    return member in values


def cache_set_add(key: str, member: str) -> None:
    """向 PostgreSQL 集合缓存追加成员。"""

    db = SessionLocal()
    try:
        row = _load_valid_entry(db, key)
        values = []
        if row and row.value:
            try:
                parsed = json.loads(row.value)
                if isinstance(parsed, list):
                    values = parsed
            except Exception:
                values = []
        if member not in values:
            values.append(member)
        if row is None:
            row = CacheEntry(key=key)
            db.add(row)
        row.value = json.dumps(values, ensure_ascii=False)
        row.value_type = "set"
        row.expires_at = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("PostgreSQL cache set add failed: key=%s error=%s", key, exc)
    finally:
        db.close()


def cache_list_get(key: str, start: int, end: int) -> list[str]:
    """从 PostgreSQL 读取列表缓存切片。"""

    values = load_json_cache(key, default=[])
    if not isinstance(values, list):
        return []
    if end == -1:
        return values[start:]
    return values[start : end + 1]


def cache_list_lpush(key: str, value: str) -> None:
    """向 PostgreSQL 列表缓存头部插入一项。"""

    db = SessionLocal()
    try:
        row = _load_valid_entry(db, key)
        values = []
        if row and row.value:
            try:
                parsed = json.loads(row.value)
                if isinstance(parsed, list):
                    values = parsed
            except Exception:
                values = []
        values.insert(0, value)
        if row is None:
            row = CacheEntry(key=key)
            db.add(row)
        row.value = json.dumps(values, ensure_ascii=False)
        row.value_type = "list"
        row.expires_at = None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("PostgreSQL cache list lpush failed: key=%s error=%s", key, exc)
    finally:
        db.close()


def cache_list_ltrim(key: str, start: int, end: int) -> None:
    """截断 PostgreSQL 列表缓存。"""

    db = SessionLocal()
    try:
        row = _load_valid_entry(db, key)
        if row is None:
            return
        values = []
        if row.value:
            try:
                parsed = json.loads(row.value)
                if isinstance(parsed, list):
                    values = parsed
            except Exception:
                values = []
        trimmed = values[start:] if end == -1 else values[start : end + 1]
        row.value = json.dumps(trimmed, ensure_ascii=False)
        row.value_type = "list"
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("PostgreSQL cache list trim failed: key=%s error=%s", key, exc)
    finally:
        db.close()
