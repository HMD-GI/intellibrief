"""通知模块导出。

职责划分：
1. 简报模块只负责生成内容。
2. 天气模块只负责查询天气数据。
3. 通知模块只负责读取发送配置并执行邮箱、飞书等外部投递。
"""

from app.modules.notification.binding_store import load_binding_settings, should_fetch_weather
from app.modules.notification.email_sender import send_email
from app.modules.notification.feishu_card import (
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)
from app.modules.notification.feishu_sender import send_feishu_robot_card

__all__ = [
    "load_binding_settings",
    "should_fetch_weather",
    "send_email",
    "build_feishu_weather_brief_card",
    "send_feishu_webhook_card",
    "send_feishu_robot_card",
]
