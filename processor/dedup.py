import hashlib
import json
import logging
from datetime import datetime

from simhash import Simhash

from app.cache import redis_client

logger = logging.getLogger(__name__)


def _keyword_hash(topic: str, keywords: list[str] | None) -> str:
    """基于主题和关键词生成稳定哈希。"""

    payload = {
        "topic": (topic or "").strip(),
        "keywords": sorted([(item or "").strip() for item in (keywords or []) if (item or "").strip()]),
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def latest_crawl_cache_key(source_id: int, topic: str, keywords: list[str] | None) -> str:
    """构造某个主题+关键词组合的最新抓取游标 Key。"""

    return f"crawl_cursor:{source_id}:{_keyword_hash(topic, keywords)}"


def load_latest_crawl_cursor(source_id: int, topic: str, keywords: list[str] | None) -> dict | None:
    """读取最新抓取游标。"""

    try:
        raw = redis_client.get(latest_crawl_cache_key(source_id, topic, keywords))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.error("读取 Redis 抓取游标失败: %s", exc)
        return None


def save_latest_crawl_cursor(
    source_id: int,
    topic: str,
    keywords: list[str] | None,
    latest_title: str,
    latest_published_at: datetime | None,
    latest_url: str,
) -> None:
    """保存最新抓取游标。

    原理：
    1. 每次抓取结束后记录该主题+关键词组合看到的最新文章。
    2. 下次再抓时，只要列表文章发布时间不晚于游标，就可以停止继续入库。
    """

    try:
        payload = {
            "title": latest_title,
            "published_at": latest_published_at.isoformat() if latest_published_at else None,
            "url": latest_url,
            "saved_at": datetime.now().isoformat(),
        }
        redis_client.set(latest_crawl_cache_key(source_id, topic, keywords), json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        logger.error("保存 Redis 抓取游标失败: %s", exc)


def is_duplicate(url: str, content: str) -> bool:
    """基于 URL 和 Simhash 做轻量去重。"""

    try:
        if redis_client.sismember("crawled_urls", url):
            return True

        if not content:
            return False

        current_hash = Simhash(content).value
        recent_hashes = redis_client.lrange("recent_simhashes", 0, -1)
        for item in recent_hashes:
            distance = bin(current_hash ^ int(item)).count("1")
            if distance < 3:
                return True

        redis_client.sadd("crawled_urls", url)
        redis_client.lpush("recent_simhashes", current_hash)
        redis_client.ltrim("recent_simhashes", 0, 10000)
        return False
    except Exception as exc:
        logger.error("去重检查失败: %s", exc)
        return False
