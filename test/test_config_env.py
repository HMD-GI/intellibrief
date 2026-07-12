import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings


class ConfigEnvTestCase(unittest.TestCase):
    """配置与大模型环境变量测试。

    测试目标：
    1. 验证 .env 中的列表、布尔值、多 Key 字符串能够被正确解析。
    2. 验证大模型配置已经收敛到统一槽位访问入口。
    """

    def test_topics_and_origins_are_loaded_from_env(self):
        self.assertIsInstance(settings.DEFAULT_TOPICS, list)
        self.assertGreaterEqual(len(settings.DEFAULT_TOPICS), 1)
        self.assertIsInstance(settings.frontend_origins_list, list)
        self.assertGreaterEqual(len(settings.frontend_origins_list), 1)

    def test_email_ssl_flag_is_loaded_from_env(self):
        self.assertIsInstance(settings.EMAIL_SMTP_USE_SSL, bool)

    def test_llm_provider_config_is_unified(self):
        first_provider = settings.get_llm_provider_config("first")
        self.assertIn("api_keys", first_provider)
        self.assertIn("model", first_provider)
        self.assertIn("base_url", first_provider)
        self.assertEqual(first_provider["model"], settings.FIRST_LLM_MODEL)
        self.assertEqual(first_provider["base_url"], settings.FIRST_LLM_BASE_URL)
        self.assertEqual(first_provider["api_keys"], settings.first_llm_keys_list)


if __name__ == "__main__":
    unittest.main()
