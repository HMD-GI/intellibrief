from datetime import datetime

from app.modules.common.settings_store import load_json_setting, save_json_setting

WEATHER_RECENT_QUERY_KEY = "weather_recent_queries"
WEATHER_RECENT_CACHE_KEY = "weather:recent"


def load_recent_queries(db, redis_client, limit: int) -> list[dict]:
    """读取最近查询地区。

    技术原理：
    1. 先读 Redis，作为热点数据缓存。
    2. Redis 没命中时再回源 PostgreSQL 配置表。
    3. 这样既有访问速度，也保留 Redis 重启后的恢复能力。
    """

    try:
        cached = redis_client.get(WEATHER_RECENT_CACHE_KEY)
        if cached:
            import json

            value = json.loads(cached)
            if isinstance(value, list):
                return value[:limit]
    except Exception:
        pass

    value = load_json_setting(db, WEATHER_RECENT_QUERY_KEY, default=[]) or []
    return value[:limit] if isinstance(value, list) else []


def save_recent_queries(db, redis_client, items: list[dict], *, limit: int, ttl: int) -> None:
    """保存最近查询地区到数据库和 Redis。"""

    trimmed_items = items[:limit]
    save_json_setting(db, WEATHER_RECENT_QUERY_KEY, trimmed_items)
    try:
        import json

        redis_client.setex(WEATHER_RECENT_CACHE_KEY, ttl, json.dumps(trimmed_items, ensure_ascii=False))
    except Exception:
        pass


def record_recent_query(db, redis_client, region: str, report: dict, *, limit: int, ttl: int) -> None:
    """记录一次最近查询。

    去重维度用 region，保证同一地区最近一次查询会顶到最前面。
    """

    normalized_region = (region or "").strip()
    if not normalized_region:
        return

    location = report.get("location") or {}
    entry = {
        "region": normalized_region,
        "display_name": location.get("display_name") or normalized_region,
        "queried_at": datetime.now().isoformat(timespec="seconds"),
        "provider": (report.get("provider") or {}).get("label") or "-",
    }

    merged = [entry]
    for item in load_recent_queries(db, redis_client, limit):
        if (item.get("region") or "").strip().lower() == normalized_region.lower():
            continue
        merged.append(item)

    save_recent_queries(db, redis_client, merged, limit=limit, ttl=ttl)
    db.commit()

