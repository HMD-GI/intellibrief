import json
import logging
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.response import fail_response, ok
from app.cache import redis_client
from app.config import settings
from app.database import get_db
from app.modules.weather import WeatherServiceError, weather_service
from app.modules.weather.recent_query_store import (
    WEATHER_RECENT_CACHE_KEY,
    WEATHER_RECENT_QUERY_KEY,
    load_recent_queries,
    record_recent_query,
)

router = APIRouter(prefix="/weather", tags=["weather"])
logger = logging.getLogger(__name__)

WEATHER_REPORT_CACHE_TTL = 60 * 20
WEATHER_SUGGEST_CACHE_TTL = 60 * 30
WEATHER_RECENT_CACHE_TTL = 60 * 60 * 24
WEATHER_RECENT_QUERY_LIMIT = 8

# 使用较宽松的中文地区名称校验规则，允许中文、空格、中点和中文括号。
CHINESE_REGION_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbf·\s（）()]{1,40}$")


def _normalize_region(region: str) -> str:
    """规范化天气查询地区。"""

    return (region or settings.DEFAULT_WEATHER_REGION).strip()


def _is_valid_chinese_region(value: str) -> bool:
    """校验地区名称是否为有效中文输入。"""

    if not value:
        return False
    return bool(CHINESE_REGION_PATTERN.fullmatch(value.strip()))


def _weather_report_cache_key(region: str) -> str:
    """生成天气详情缓存键。"""

    return f"weather:report:{region.lower()}"


def _weather_suggest_cache_key(keyword: str) -> str:
    """生成地区联想缓存键。"""

    return f"weather:suggest:{keyword.lower()}"


def _load_cached_json(key: str) -> dict | list | None:
    """从缓存层读取 JSON 数据。"""

    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("Weather redis cache read failed: key=%s error=%s", key, exc)
        return None


def _save_cached_json(key: str, value: dict | list, ttl: int) -> None:
    """写入缓存层 JSON 数据。"""

    try:
        redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        logger.warning("Weather redis cache write failed: key=%s error=%s", key, exc)


@router.get("/report")
def get_weather_report(
    region: str = Query("", description="查询地区，例如：北京、上海浦东"),
    db: Session = Depends(get_db),
):
    """获取指定地区当天天气、预警和台风信息。"""

    target_region = _normalize_region(region)
    if not _is_valid_chinese_region(target_region):
        return fail_response(
            "请输入有效的中文地区名称。",
            code=400,
            status_code=400,
            data={"region": target_region},
        )

    cache_key = _weather_report_cache_key(target_region)
    cached_report = _load_cached_json(cache_key)
    if isinstance(cached_report, dict):
        record_recent_query(
            db,
            redis_client,
            target_region,
            cached_report,
            limit=WEATHER_RECENT_QUERY_LIMIT,
            ttl=WEATHER_RECENT_CACHE_TTL,
        )
        return ok({"report": cached_report}, "天气查询成功。")

    try:
        report = weather_service.get_daily_weather_report(target_region)
    except WeatherServiceError as exc:
        return fail_response(
            str(exc),
            code=400,
            status_code=400,
            data={"region": target_region},
        )
    except Exception as exc:
        return fail_response(
            f"天气服务调用失败：{exc}",
            code=502,
            status_code=502,
            data={"region": target_region},
        )

    _save_cached_json(cache_key, report, WEATHER_REPORT_CACHE_TTL)
    record_recent_query(
        db,
        redis_client,
        target_region,
        report,
        limit=WEATHER_RECENT_QUERY_LIMIT,
        ttl=WEATHER_RECENT_CACHE_TTL,
    )
    return ok({"report": report}, "天气查询成功。")


@router.get("/suggest")
def get_weather_suggestions(
    keyword: str = Query("", description="地区关键字，例如：北、上海、浦东"),
    db: Session = Depends(get_db),
):
    """获取地区联想结果。"""

    target_keyword = (keyword or "").strip()
    if not target_keyword:
        recent_items = load_recent_queries(db, redis_client, WEATHER_RECENT_QUERY_LIMIT)
        items = [
            {
                "region": item.get("region") or "",
                "display_name": item.get("display_name") or item.get("region") or "",
                "source": "recent",
            }
            for item in recent_items
        ]
        return ok({"items": items}, "最近查询加载成功。")

    if not _is_valid_chinese_region(target_keyword):
        return fail_response(
            "请输入有效的中文地区名称。",
            code=400,
            status_code=400,
            data={"keyword": target_keyword},
        )

    cache_key = _weather_suggest_cache_key(target_keyword)
    cached_items = _load_cached_json(cache_key)
    if isinstance(cached_items, list):
        return ok({"items": cached_items}, "地区联想查询成功。")

    try:
        suggestions = weather_service.search_locations(target_keyword)
    except WeatherServiceError as exc:
        return fail_response(
            str(exc),
            code=400,
            status_code=400,
            data={"keyword": target_keyword},
        )
    except Exception as exc:
        return fail_response(
            f"地区联想查询失败：{exc}",
            code=502,
            status_code=502,
            data={"keyword": target_keyword},
        )

    items = [
        {
            "region": item.get("name") or target_keyword,
            "display_name": item.get("display_name") or item.get("name") or target_keyword,
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "tz": item.get("tz"),
            "source": "provider",
        }
        for item in suggestions
    ]
    _save_cached_json(cache_key, items, WEATHER_SUGGEST_CACHE_TTL)
    return ok({"items": items}, "地区联想查询成功。")


@router.get("/recent")
def get_recent_weather_queries(db: Session = Depends(get_db)):
    """获取最近查询地区列表。"""

    return ok({"items": load_recent_queries(db, redis_client, WEATHER_RECENT_QUERY_LIMIT)}, "最近查询加载成功。")


__all__ = [
    "router",
    "WEATHER_REPORT_CACHE_TTL",
    "WEATHER_SUGGEST_CACHE_TTL",
    "WEATHER_RECENT_CACHE_TTL",
    "WEATHER_RECENT_QUERY_LIMIT",
    "WEATHER_RECENT_QUERY_KEY",
    "WEATHER_RECENT_CACHE_KEY",
]
