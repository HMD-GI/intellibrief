import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.notification import should_fetch_weather  # noqa: E402
from app.modules.notification.feishu_card import build_feishu_weather_brief_card  # noqa: E402
from app.modules.notification.feishu_sender import send_feishu_robot_card  # noqa: E402
from app.modules.notification.message_fragments import (  # noqa: E402
    render_brief_lines,
    render_typhoon_lines,
    render_weather_lines,
)


class NotificationModuleTestCase(unittest.TestCase):
    """通知模块聚合测试。"""

    def test_should_fetch_weather(self):
        """任一通道勾选天气或台风时才查询天气。"""

        bindings = {
            "email": {
                "include_brief": True,
                "include_weather": True,
                "include_typhoon": False,
            },
            "feishu": {
                "webhook_url": "",
                "include_brief": False,
                "include_weather": False,
                "include_typhoon": False,
            },
        }
        self.assertTrue(should_fetch_weather(bindings))
        self.assertFalse(should_fetch_weather({"email": {"include_brief": True}}))

    @patch("app.modules.notification.feishu_sender.send_feishu_webhook_card")
    @patch("app.modules.notification.feishu_sender.build_feishu_weather_brief_card")
    @patch("app.modules.notification.feishu_sender.load_binding_settings")
    def test_send_feishu_robot_card_uses_webhook_settings(
        self,
        mock_load_binding_settings,
        mock_build_card,
        mock_send_webhook,
    ):
        """飞书发送器会读取配置并调用 Webhook。"""

        mock_load_binding_settings.return_value = {
            "feishu": {
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/demo",
                "include_brief": True,
                "include_weather": True,
                "include_typhoon": True,
            }
        }
        mock_build_card.return_value = {"header": {"title": {"content": "demo"}}, "elements": []}

        send_feishu_robot_card(
            brief_date=date(2026, 7, 13),
            weather_report={"region": "北京"},
            briefs=[
                {
                    "title": "IntelliBrief AI资讯每日简报 - 2026-07-13",
                    "topic": "AI资讯",
                    "date": "2026-07-13",
                    "url": "http://127.0.0.1:8000/briefs/item/1/html",
                }
            ],
        )

        self.assertEqual(mock_build_card.call_count, 1)
        self.assertEqual(mock_send_webhook.call_count, 1)
        self.assertEqual(
            mock_send_webhook.call_args.args[0],
            "https://open.feishu.cn/open-apis/bot/v2/hook/demo",
        )

    def test_typhoon_content_only_contains_current_point_details(self):
        """台风通知只包含当前点位，不包含未来预测。"""

        weather_report = {
            "typhoon": {
                "summary": "当前日期前后一周内监测到 1 个台风：巴威",
                "alerts": [],
                "active": [
                    {
                        "name": "巴威",
                        "forecast": [
                            {"fxTime": "2026-07-13T04:00+08:00", "text": "未来预测"},
                        ],
                        "current_point": {
                            "fxTime": "2026-07-12T16:00+08:00",
                            "lat": "31.4",
                            "lon": "118.4",
                            "windSpeed": "23",
                            "pressure": "988",
                            "text": "当前点",
                        },
                    }
                ],
            },
        }

        lines = render_typhoon_lines(weather_report)
        self.assertTrue(any("2026-07-12T16:00+08:00" in line for line in lines))
        self.assertFalse(any("未来预测" in line for line in lines))

    def test_weather_lines_match_broadcast_style(self):
        """天气分时文本使用旧播报格式。"""

        weather_report = {
            "hourly": [
                {
                    "fxTime": "2026-07-13T10:00+08:00",
                    "text": "多云",
                    "temp": 33,
                    "pop": 5,
                    "humidity": 67,
                }
            ]
        }
        lines = render_weather_lines(weather_report)
        self.assertEqual(lines[0], "10:00 ⛅ 多云 | 33°C | 降雨 5% | 湿度 67%")

    def test_brief_lines_support_multiple_briefs(self):
        """一条通知里可以展开多份简报。"""

        lines = render_brief_lines(
            [
                {
                    "title": "IntelliBrief 国外新闻每日简报 - 2026-07-13",
                    "topic": "国外新闻",
                    "date": "2026-07-13",
                    "url": "http://127.0.0.1:8000/briefs/item/1/html",
                },
                {
                    "title": "IntelliBrief AI资讯每日简报 - 2026-07-13",
                    "topic": "AI资讯",
                    "date": "2026-07-13",
                    "url": "http://127.0.0.1:8000/briefs/item/2/html",
                },
            ]
        )

        joined = "\n".join(lines)
        self.assertIn("IntelliBrief 国外新闻每日简报 - 2026-07-13", joined)
        self.assertIn("IntelliBrief AI资讯每日简报 - 2026-07-13", joined)
        self.assertEqual(joined.count("🔗 链接："), 2)

    def test_feishu_card_combines_multiple_briefs_in_one_section(self):
        """飞书卡片可在一条消息中展示多份简报。"""

        card = build_feishu_weather_brief_card(
            weather_report={"region": "北京", "date": "2026-07-13", "provider": {"label": "和风天气"}},
            briefs=[
                {
                    "title": "IntelliBrief 国外新闻每日简报 - 2026-07-13",
                    "topic": "国外新闻",
                    "date": "2026-07-13",
                    "url": "http://127.0.0.1:8000/briefs/item/1/html",
                },
                {
                    "title": "IntelliBrief AI资讯每日简报 - 2026-07-13",
                    "topic": "AI资讯",
                    "date": "2026-07-13",
                    "url": "http://127.0.0.1:8000/briefs/item/2/html",
                },
            ],
            include_brief=True,
            include_weather=False,
            include_typhoon=False,
            brief_date=date(2026, 7, 13),
        )

        card_text = str(card)
        self.assertIn("IntelliBrief 国外新闻每日简报 - 2026-07-13", card_text)
        self.assertIn("IntelliBrief AI资讯每日简报 - 2026-07-13", card_text)
        self.assertEqual(card_text.count("🔗 链接："), 2)


if __name__ == "__main__":
    unittest.main()
