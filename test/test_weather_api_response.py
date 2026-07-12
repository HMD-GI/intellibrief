import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bootstrap import PROJECT_ROOT  # noqa: F401  # 确保测试运行时项目根目录在导入路径中。
from app.database import get_db
from app.main import app


class WeatherApiResponseTestCase(unittest.TestCase):
    """验证天气接口统一响应格式与中文地区校验。"""

    def setUp(self):
        # 使用轻量级假依赖替换数据库会话，避免测试依赖真实数据库状态。
        app.dependency_overrides[get_db] = lambda: object()
        self.client = TestClient(app)

    def tearDown(self):
        # 每个测试结束后清理依赖覆盖，避免污染其它测试。
        app.dependency_overrides.clear()

    @patch("app.api.weather.record_recent_query")
    @patch("app.api.weather._save_cached_json")
    @patch("app.api.weather._load_cached_json", return_value=None)
    @patch("app.api.weather.weather_service.get_daily_weather_report")
    def test_weather_report_returns_unified_payload(
        self,
        mock_report,
        _mock_cache_read,
        _mock_cache_write,
        _mock_recent,
    ):
        # 构造一个最小可用的天气报告，验证接口会放入 data.report。
        mock_report.return_value = {
            "region": "北京",
            "date": "2026-07-11",
            "hourly": [],
            "warnings": [],
            "typhoon": {"summary": "暂无台风信息", "active": []},
            "provider": {"label": "和风天气"},
            "weather_summary": {"temp_min": 20, "temp_max": 30, "hourly_count": 0},
            "notices": [],
        }

        response = self.client.get("/weather/report", params={"region": "北京"})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["message"], "天气查询成功。")
        self.assertIn("report", payload["data"])
        self.assertEqual(payload["data"]["report"]["region"], "北京")

    def test_weather_report_rejects_invalid_region(self):
        # 输入纯问号时，应直接返回统一错误结构，而不是继续请求第三方服务。
        response = self.client.get("/weather/report", params={"region": "??"})
        payload = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], 400)
        self.assertEqual(payload["message"], "请输入有效的中文地区名称。")
        self.assertEqual(payload["data"]["region"], "??")

    def test_weather_suggest_rejects_invalid_keyword(self):
        # 联想接口也必须拦截非法输入，避免后端无意义查询第三方接口。
        response = self.client.get("/weather/suggest", params={"keyword": "??"})
        payload = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], 400)
        self.assertEqual(payload["message"], "请输入有效的中文地区名称。")
        self.assertEqual(payload["data"]["keyword"], "??")


if __name__ == "__main__":
    unittest.main()
