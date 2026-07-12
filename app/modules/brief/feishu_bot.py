"""飞书卡片兼容层。

说明：
1. 飞书机器人卡片实现已迁移到 `app.modules.notification.feishu_card`。
2. 保留该文件是为了兼容旧测试和旧导入路径。
"""

from app.modules.notification.feishu_card import (
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)

__all__ = [
    "build_feishu_weather_brief_card",
    "send_feishu_webhook_card",
]
