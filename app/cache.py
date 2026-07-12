import logging

import redis

from app.config import settings
from app.database import Base, engine
from app.models.cache_entry import CacheEntry
from app.modules.common.cache_store import (
    cache_list_get,
    cache_list_lpush,
    cache_list_ltrim,
    cache_set_add,
    cache_set_contains,
    load_text_cache,
    save_text_cache,
)

logger = logging.getLogger(__name__)

# 提前确保缓存表存在。
# 原因：
# 1. 天气接口和缓存模块可能在 app.main 之前被单独导入。
# 2. 提前建表可以避免测试或独立模块调用时出现“缓存表不存在”错误。
Base.metadata.create_all(bind=engine, tables=[CacheEntry.__table__])


def _build_redis_client() -> redis.Redis | None:
    """尝试构建可用的 Redis 客户端。

    技术说明：
    1. Redis 在这里是热缓存，不再是启动硬依赖。
    2. 连接失败时返回 None，后续自动回退到 PostgreSQL。
    """

    urls = [settings.REDIS_URL]
    if settings.REDIS_FALLBACK_URL and settings.REDIS_FALLBACK_URL not in urls:
        urls.append(settings.REDIS_FALLBACK_URL)

    for url in urls:
        try:
            client = redis.from_url(url, decode_responses=True)
            client.ping()
            logger.info("Redis connected: %s", url)
            return client
        except Exception as exc:
            logger.warning("Redis connect failed for %s: %s", url, exc)
    logger.warning("Redis unavailable, cache will fallback to PostgreSQL.")
    return None


class HybridCache:
    """混合缓存客户端。

    技术原理：
    1. 读操作优先查 Redis，失败后立即回退 PostgreSQL。
    2. 写操作同时写 PostgreSQL，Redis 仅作为热缓存副本。
    3. 这样既能保留 Redis 性能优势，也能在 Redis 未启动时保证业务可用。
    """

    def __init__(self, client: redis.Redis | None = None):
        self._client = client

    def _mark_redis_unavailable(self, action: str, error: Exception) -> None:
        """标记 Redis 不可用，避免后续重复报错。"""

        logger.warning("Redis %s failed, fallback to PostgreSQL: %s", action, error)
        self._client = None

    def get(self, key: str):
        """读取字符串缓存。"""

        if self._client is not None:
            try:
                return self._client.get(key)
            except Exception as exc:
                self._mark_redis_unavailable(f"get({key})", exc)
        return load_text_cache(key)

    def set(self, key: str, value):
        """写入无过期时间的字符串缓存。"""

        value_str = value if isinstance(value, str) else str(value)
        save_text_cache(key, value_str)
        if self._client is not None:
            try:
                return self._client.set(key, value_str)
            except Exception as exc:
                self._mark_redis_unavailable(f"set({key})", exc)
        return True

    def setex(self, key: str, ttl: int, value):
        """写入带过期时间的字符串缓存。"""

        value_str = value if isinstance(value, str) else str(value)
        save_text_cache(key, value_str, ttl_seconds=ttl)
        if self._client is not None:
            try:
                return self._client.setex(key, ttl, value_str)
            except Exception as exc:
                self._mark_redis_unavailable(f"setex({key})", exc)
        return True

    def sismember(self, key: str, member: str) -> bool:
        """检查集合成员是否存在。"""

        if self._client is not None:
            try:
                return bool(self._client.sismember(key, member))
            except Exception as exc:
                self._mark_redis_unavailable(f"sismember({key})", exc)
        return cache_set_contains(key, member)

    def sadd(self, key: str, member: str):
        """向集合添加成员。"""

        cache_set_add(key, member)
        if self._client is not None:
            try:
                return self._client.sadd(key, member)
            except Exception as exc:
                self._mark_redis_unavailable(f"sadd({key})", exc)
        return 1

    def lrange(self, key: str, start: int, end: int):
        """读取列表切片。"""

        if self._client is not None:
            try:
                return self._client.lrange(key, start, end)
            except Exception as exc:
                self._mark_redis_unavailable(f"lrange({key})", exc)
        return cache_list_get(key, start, end)

    def lpush(self, key: str, value):
        """向列表头部插入元素。"""

        value_str = value if isinstance(value, str) else str(value)
        cache_list_lpush(key, value_str)
        if self._client is not None:
            try:
                return self._client.lpush(key, value_str)
            except Exception as exc:
                self._mark_redis_unavailable(f"lpush({key})", exc)
        return 1

    def ltrim(self, key: str, start: int, end: int):
        """截断列表。"""

        cache_list_ltrim(key, start, end)
        if self._client is not None:
            try:
                return self._client.ltrim(key, start, end)
            except Exception as exc:
                self._mark_redis_unavailable(f"ltrim({key})", exc)
        return True

    @property
    def available(self) -> bool:
        """返回 Redis 当前是否可用。"""

        return self._client is not None


redis_client = HybridCache(_build_redis_client())
