import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.notification.feishu_card import (
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)


class FeishuBotModuleTestCase(unittest.TestCase):
    """飞书机器人卡片模块测试。"""

    def test_build_card_contains_weather_typhoon_and_brief_sections(self):
        weather_report = {
            "region": "北京",
            "date": "2026-07-06",
            "provider": {"label": "MockWeather"},
            "weather_summary": {"temp_min": 24, "temp_max": 33},
            "hourly": [
                {
                    "fxTime": "2026-07-06T08:00+08:00",
                    "text": "晴",
                    "temp": 29,
                    "pop": 10,
                    "humidity": 55,
                }
            ],
            "warnings": [
                {"title": "大风预警", "text": "局部短时大风"},
            ],
            "typhoon": {
                "summary": "当前无明显台风影响",
                "active": [],
            },
            "notices": ["自动降级为备用天气源"],
        }

        card = build_feishu_weather_brief_card(
            weather_report=weather_report,
            brief_title="IntelliBrief 国外新闻每日简报 - 2026-07-06",
            brief_topic="国外新闻",
            brief_date=date(2026, 7, 6),
            brief_url="http://127.0.0.1:8000/briefs/item/1/html",
            include_brief=True,
            include_weather=True,
            include_typhoon=True,
        )

        self.assertEqual(card["header"]["title"]["content"], "北京 天气与简报播报")
        joined = str(card["elements"])
        self.assertIn("全天分时天气", joined)
        self.assertIn("台风情况", joined)
        self.assertIn("发送简报", joined)
        self.assertIn("查看简报", joined)

    @patch("app.modules.notification.feishu_card.requests.post")
    def test_send_feishu_webhook_card(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 0, "msg": "success"}
        mock_post.return_value = response

        send_feishu_webhook_card(
            "https://open.feishu.cn/open-apis/bot/v2/hook/demo",
            {"header": {"title": {"content": "demo"}}, "elements": []},
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertIn("card", payload)


if __name__ == "__main__":
    unittest.main()
