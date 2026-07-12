import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.notification import should_fetch_weather
from app.modules.notification.feishu_sender import send_feishu_robot_card


class NotificationModuleTestCase(unittest.TestCase):
    """通知模块聚合测试。"""

    def test_should_fetch_weather(self):
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
            brief_url="http://127.0.0.1:8000/briefs/item/1/html",
            brief_title="IntelliBrief AI资讯每日简报 - 2026-07-06",
            brief_topic="AI资讯",
            brief_date=date(2026, 7, 6),
            weather_report={"region": "北京"},
        )

        self.assertEqual(mock_build_card.call_count, 1)
        self.assertEqual(mock_send_webhook.call_count, 1)
        self.assertEqual(
            mock_send_webhook.call_args.args[0],
            "https://open.feishu.cn/open-apis/bot/v2/hook/demo",
        )


if __name__ == "__main__":
    unittest.main()
