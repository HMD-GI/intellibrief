import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.notification.feishu_card import (  # noqa: E402
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)


class FeishuBotModuleTestCase(unittest.TestCase):
    """飞书机器人卡片模块测试。"""

    def test_build_card_contains_weather_typhoon_and_brief_sections(self):
        weather_report = {
            "region": "东莞",
            "date": "2026-07-13",
            "provider": {"label": "和风天气"},
            "weather_summary": {"temp_min": 28, "temp_max": 35},
            "hourly": [
                {
                    "fxTime": "2026-07-13T10:00+08:00",
                    "text": "多云",
                    "temp": 33,
                    "pop": 5,
                    "humidity": 67,
                }
            ],
            "typhoon": {
                "summary": "当前日期前后一周内监测到 1 个台风：巴威",
                "active": [
                    {
                        "name": "巴威",
                        "current_point": {
                            "fxTime": "2026-07-13T08:00+08:00",
                            "lat": "33.4",
                            "lon": "117.9",
                            "windSpeed": "20",
                            "pressure": "992",
                            "text": "热带风暴",
                        },
                    }
                ],
            },
        }

        card = build_feishu_weather_brief_card(
            weather_report=weather_report,
            brief_title="IntelliBrief 国外新闻每日简报 - 2026-07-13",
            brief_topic="国外新闻",
            brief_date=date(2026, 7, 13),
            brief_url="http://127.0.0.1:8000/briefs/item/1/html",
            include_brief=True,
            include_weather=True,
            include_typhoon=True,
        )

        self.assertEqual(card["header"]["title"]["content"], "东莞 天气与简报播报")
        joined = str(card["elements"])
        self.assertIn("全天分时天气", joined)
        self.assertIn("台风情况", joined)
        self.assertIn("发送简报", joined)
        self.assertIn("查看简报", joined)
        self.assertIn("🌀 巴威", joined)

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
