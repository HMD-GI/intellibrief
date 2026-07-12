import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.weather import WEATHER_RECENT_QUERY_KEY, router as weather_router
from app.database import SessionLocal
from app.models.setting import AppSetting
from app.services.weather_service import OpenMeteoService, WeatherService, WeatherServiceError
from brief.notifier import should_fetch_weather


class WeatherApiTestCase(unittest.TestCase):
    """天气接口测试。

    测试思路：
    1. 路由层使用 mock 隔离第三方天气服务。
    2. 最近查询使用真实数据库设置表，验证接口读写链路。
    3. Redis 使用 mock，避免测试受缓存状态干扰。
    """

    def setUp(self):
        app = FastAPI()
        app.include_router(weather_router)
        self.client = TestClient(app)
        self.db = SessionLocal()
        self.original_recent_row = self.db.query(AppSetting).filter(AppSetting.key == WEATHER_RECENT_QUERY_KEY).first()
        self.original_recent_value = self.original_recent_row.value if self.original_recent_row else None

    def tearDown(self):
        row = self.db.query(AppSetting).filter(AppSetting.key == WEATHER_RECENT_QUERY_KEY).first()
        if self.original_recent_value is None:
            if row:
                self.db.delete(row)
        else:
            if row:
                row.value = self.original_recent_value
            else:
                self.db.add(AppSetting(key=WEATHER_RECENT_QUERY_KEY, value=self.original_recent_value))
        self.db.commit()
        self.db.close()

    @patch("app.api.weather.redis_client")
    @patch("app.api.weather.weather_service.get_daily_weather_report")
    def test_weather_report_success(self, mock_get_report, mock_redis):
        mock_redis.get.return_value = None
        report = {
            "region": "北京",
            "date": "2026-07-05",
            "provider": {"name": "qweather", "label": "和风天气", "mode": "primary"},
            "capabilities": {"warning": True, "typhoon": True},
            "location": {"id": "101010100", "name": "北京", "display_name": "中国 / 北京 / 北京"},
            "hourly": [{"fxTime": "2026-07-05T08:00+08:00", "temp": "30", "text": "晴"}],
            "weather_summary": {"temp_min": 28, "temp_max": 35, "hourly_count": 1},
            "warnings": [],
            "typhoon": {
                "has_active": False,
                "summary": "当前未查询到台风预警或台风活动。",
                "alerts": [],
                "active": [],
                "provider_supported": True,
            },
            "notices": [],
            "fetched_at": "2026-07-05T08:30:00+08:00",
        }
        mock_get_report.return_value = report

        response = self.client.get("/weather/report", params={"region": "\u5317\u4eac"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["report"]["region"], "\u5317\u4eac")
        self.assertEqual(payload["data"]["report"]["provider"]["label"], "\u548c\u98ce\u5929\u6c14")
        self.assertTrue(
            any(call.args[0] == "weather:report:\u5317\u4eac" for call in mock_redis.setex.call_args_list)
        )
    @patch("app.api.weather.redis_client")
    @patch("app.api.weather.weather_service.get_daily_weather_report")
    def test_weather_report_failure(self, mock_get_report, mock_redis):
        mock_redis.get.return_value = None
        mock_get_report.side_effect = WeatherServiceError("未配置天气 Key")

        response = self.client.get("/weather/report", params={"region": "\u5317\u4eac"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("未配置天气 Key", response.text)

    @patch("app.api.weather.redis_client")
    @patch("app.api.weather.weather_service.search_locations")
    def test_weather_suggest_success(self, mock_search_locations, mock_redis):
        mock_redis.get.return_value = None
        mock_search_locations.return_value = [
            {
                "name": "北京",
                "display_name": "中国 / 北京 / 北京",
                "lat": 39.9,
                "lon": 116.4,
                "tz": "Asia/Shanghai",
            }
        ]

        response = self.client.get("/weather/suggest", params={"keyword": "\u5317"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["items"][0]["region"], "\u5317\u4eac")
        self.assertTrue(
            any(call.args[0] == "weather:suggest:\u5317" for call in mock_redis.setex.call_args_list)
        )
    @patch("app.api.weather.redis_client")
    def test_weather_recent_and_empty_suggest(self, mock_redis):
        mock_redis.get.return_value = None
        row = self.db.query(AppSetting).filter(AppSetting.key == WEATHER_RECENT_QUERY_KEY).first()
        value = [
            {
                "region": "北京",
                "display_name": "中国 / 北京 / 北京",
                "queried_at": "2026-07-05T20:10:00",
                "provider": "和风天气",
            }
        ]
        if row:
            row.value = json.dumps(value, ensure_ascii=False)
        else:
            self.db.add(AppSetting(key=WEATHER_RECENT_QUERY_KEY, value=json.dumps(value, ensure_ascii=False)))
        self.db.commit()

        recent_response = self.client.get("/weather/recent")
        self.assertEqual(recent_response.status_code, 200)
        self.assertEqual(recent_response.json()["data"]["items"][0]["region"], "\u5317\u4eac")

        suggest_response = self.client.get("/weather/suggest", params={"keyword": ""})
        self.assertEqual(suggest_response.status_code, 200)
        self.assertEqual(suggest_response.json()["data"]["items"][0]["source"], "recent")

    def test_delivery_option_requires_weather(self):
        bindings = {
            "email": {
                "include_brief": True,
                "include_weather": True,
                "include_typhoon": False,
            },
            "feishu": {
                "include_brief": True,
                "include_weather": False,
                "include_typhoon": False,
            },
        }
        self.assertTrue(should_fetch_weather(bindings))
        self.assertFalse(should_fetch_weather({"email": {"include_brief": True}}))


class QWeatherRequestTestCase(unittest.TestCase):
    """???????????"""

    def test_qweather_request_uses_header_and_official_geo_path(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        captured = {}

        def fake_request_json(url, *, params=None, headers=None, optional=False, method="GET", json_body=None):
            captured["url"] = url
            captured["params"] = params or {}
            captured["headers"] = headers or {}
            return {"code": "200", "location": []}

        service._request_json = fake_request_json
        service._qweather_request_json(
            "/geo/v2/city/lookup",
            base_url="https://your-api-host",
            params={"location": "??", "number": 8, "lang": "zh"},
        )

        self.assertEqual(captured["params"].get("location"), "??")
        self.assertEqual(captured["headers"].get("X-QW-Api-Key"), "demo-key")
        self.assertTrue(captured["url"].endswith("/geo/v2/city/lookup"))

    def test_qweather_lookup_location_prefers_official_geo_path(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        call_paths = []

        def fake_qweather_request_json(path, *, base_url, params=None, optional=False):
            call_paths.append(path)
            if path == "/geo/v2/city/lookup":
                return {
                    "code": "200",
                    "location": [
                        {
                            "id": "101010100",
                            "name": "??",
                            "adm1": "??",
                            "adm2": "??",
                            "country": "??",
                            "lat": "39.90",
                            "lon": "116.40",
                            "tz": "Asia/Shanghai",
                        }
                    ],
                }
            return {"code": "200", "location": []}

        service._qweather_request_json = fake_qweather_request_json
        locations = service._lookup_locations("??")
        self.assertEqual(len(locations), 1)
        self.assertEqual(call_paths, ["/geo/v2/city/lookup"])

    def test_qweather_typhoon_list_uses_official_params(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        captured_calls = []

        def fake_qweather_request_json(path, *, base_url, params=None, optional=False):
            captured_calls.append((path, params or {}))
            return {"code": "200", "storm": []}

        service._qweather_request_json = fake_qweather_request_json
        service._fetch_typhoon_list()

        self.assertTrue(captured_calls)
        first_path, first_params = captured_calls[0]
        self.assertEqual(first_path, "/v7/tropical/storm-list")
        self.assertEqual(first_params.get("basin"), "NP")
        self.assertIn("year", first_params)

    def test_qweather_typhoon_returns_empty_message_when_week_has_no_storm(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        service._fetch_typhoon_list = Mock(return_value=[])

        result = service._fetch_typhoon({"name": "温州"}, [])

        self.assertFalse(result["has_active"])
        self.assertEqual(result["summary"], "当前日期前后一周内没有台风")
        self.assertEqual(result["active"], [])

    def test_qweather_typhoon_track_merges_now_and_history_points(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        service._qweather_request_json = Mock(
            return_value={
                "code": "200",
                "now": {
                    "pubTime": "2026-07-12T16:00+08:00",
                    "lat": "31.4",
                    "lon": "118.4",
                    "pressure": "988",
                    "windSpeed": "23",
                },
                "track": [
                    {
                        "time": "2026-07-11T16:00+08:00",
                        "lat": "30.6",
                        "lon": "119.2",
                        "pressure": "992",
                        "windSpeed": "20",
                    }
                ],
            }
        )

        items = service._fetch_typhoon_track("NP_2609")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["fxTime"], "2026-07-11T16:00+08:00")
        self.assertEqual(items[1]["fxTime"], "2026-07-12T16:00+08:00")

    def test_qweather_typhoon_track_keeps_latest_middle_day_points(self):
        from app.services.weather_service import QWeatherService

        service = QWeatherService(api_key="demo-key")
        history_points = []
        start_time = datetime.fromisoformat("2026-07-05T00:00:00+08:00")
        for index in range(90):
            point_time = start_time + timedelta(hours=index * 3)
            history_points.append(
                {
                    "time": point_time.isoformat(),
                    "lat": f"{20 + index * 0.1:.1f}",
                    "lon": f"{130 - index * 0.1:.1f}",
                    "pressure": "950",
                    "windSpeed": "35",
                }
            )

        service._qweather_request_json = Mock(
            return_value={
                "code": "200",
                "track": history_points,
            }
        )

        items = service._fetch_typhoon_track("NP_2609")

        # 这里重点验证 7 月 11 日的中间历史点不会再被“最早 72 个点”错误截断。
        self.assertTrue(any(item["fxTime"].startswith("2026-07-11") for item in items))


class WeatherFallbackTestCase(unittest.TestCase):
    """天气服务降级测试。"""

    def test_weather_service_falls_back_to_openmeteo(self):
        service = WeatherService()
        report = {
            "region": "北京",
            "date": "2026-07-05",
            "provider": {"name": "openmeteo", "label": "Open-Meteo", "mode": "primary"},
            "capabilities": {"warning": False, "typhoon": False},
            "location": {"id": "1", "name": "北京"},
            "hourly": [],
            "weather_summary": {"temp_min": 20, "temp_max": 30, "hourly_count": 0},
            "warnings": [],
            "typhoon": {
                "has_active": False,
                "summary": "当前使用免费备用天气源。",
                "alerts": [],
                "active": [],
                "provider_supported": False,
            },
            "notices": [],
            "fetched_at": "2026-07-05T08:30:00+08:00",
        }

        service.qweather = Mock()
        service.openmeteo = Mock()
        service.qweather.provider_name = "qweather"
        service.qweather.provider_label = "和风天气"
        service.openmeteo.provider_name = "openmeteo"
        service.openmeteo.provider_label = "Open-Meteo"
        service.qweather.get_daily_weather_report.side_effect = WeatherServiceError("额度不足")
        service.openmeteo.get_daily_weather_report.return_value = report
        service._provider_chain = Mock(return_value=[(service.qweather, "primary"), (service.openmeteo, "fallback")])

        result = service.get_daily_weather_report("北京")
        self.assertEqual(result["provider"]["name"], "openmeteo")
        self.assertEqual(result["provider"]["mode"], "fallback")
        self.assertTrue(any("额度不足" in item for item in result["notices"]))

    def test_openmeteo_typhoon_is_graceful_degradation(self):
        service = OpenMeteoService()
        service._lookup_locations = Mock(
            return_value=[
                {
                    "id": "1",
                    "name": "北京",
                    "admin1": "北京",
                    "admin2": "北京",
                    "country": "中国",
                    "latitude": 39.9,
                    "longitude": 116.4,
                    "timezone": "Asia/Shanghai",
                }
            ]
        )
        service._fetch_hourly_weather = Mock(
            return_value=[
                {
                    "fxTime": "2026-07-05T08:00+08:00",
                    "temp": 30,
                    "text": "晴",
                    "windDir": "北",
                    "windScale": "2级",
                    "humidity": 60,
                    "precip": 0,
                    "pop": 0,
                }
            ]
        )

        result = service.get_daily_weather_report("北京")
        self.assertEqual(result["provider"]["name"], "openmeteo")
        self.assertFalse(result["typhoon"]["provider_supported"])
        self.assertTrue(result["notices"])


if __name__ == "__main__":
    unittest.main()
