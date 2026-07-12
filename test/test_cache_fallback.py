import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import HybridCache
from app.database import SessionLocal
from app.models.cache_entry import CacheEntry


class CacheFallbackTestCase(unittest.TestCase):
    """Redis 失效时的 PostgreSQL 回退测试。"""

    def setUp(self):
        self.cache = HybridCache(client=None)
        self.db = SessionLocal()
        self.prefix = "test:cache:fallback:"

    def tearDown(self):
        self.db.query(CacheEntry).filter(CacheEntry.key.like(f"{self.prefix}%")).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()

    def test_text_cache_fallback(self):
        key = f"{self.prefix}text"
        self.cache.setex(key, 60, "hello")
        self.assertEqual(self.cache.get(key), "hello")

    def test_set_cache_fallback(self):
        key = f"{self.prefix}set"
        self.cache.sadd(key, "article-1")
        self.assertTrue(self.cache.sismember(key, "article-1"))
        self.assertFalse(self.cache.sismember(key, "article-2"))

    def test_list_cache_fallback(self):
        key = f"{self.prefix}list"
        self.cache.lpush(key, "1")
        self.cache.lpush(key, "2")
        self.cache.ltrim(key, 0, 0)
        self.assertEqual(self.cache.lrange(key, 0, -1), ["2"])


if __name__ == "__main__":
    unittest.main()
