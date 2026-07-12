"""通知兼容层。

技术说明：
1. 旧代码大量从 `brief.notifier` 直接导入发送函数。
2. 当前项目已经将发送能力拆到 `app.modules.notification`。
3. 这里保留一个薄包装层，既不打破旧调用方，又把真实实现收敛到独立通知模块。
"""

from app.modules.notification import (
    load_binding_settings,
    send_email,
    send_feishu_robot_card,
    should_fetch_weather,
)

__all__ = [
    "load_binding_settings",
    "send_email",
    "send_feishu_robot_card",
    "should_fetch_weather",
]
