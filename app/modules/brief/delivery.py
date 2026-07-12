"""简报模块兼容层。

说明：
1. 通知能力已经迁移到 `app.modules.notification`。
2. 这里保留旧导入路径，避免历史调用点直接失效。
"""

from app.modules.notification import (
    build_feishu_weather_brief_card,
    load_binding_settings,
    send_email,
    send_feishu_robot_card,
    send_feishu_webhook_card,
    should_fetch_weather,
)

__all__ = [
    "load_binding_settings",
    "should_fetch_weather",
    "send_email",
    "send_feishu_robot_card",
    "build_feishu_weather_brief_card",
    "send_feishu_webhook_card",
]
