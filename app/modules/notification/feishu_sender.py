import logging
from datetime import date

from app.modules.notification.binding_store import channel_options, load_binding_settings
from app.modules.notification.feishu_card import (
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)

logger = logging.getLogger(__name__)


def send_feishu_robot_card(
    brief_url: str | None,
    brief_title: str | None,
    brief_topic: str | None,
    brief_date: date,
    weather_report: dict | None = None,
) -> None:
    """通过飞书机器人发送卡片消息。

    技术原理：
    1. 使用 Webhook 直接发送 interactive card。
    2. 天气、台风、简报三段独立成卡片区块。
    """

    bindings = load_binding_settings()
    feishu_binding = bindings.get("feishu", {})
    options = channel_options(feishu_binding)
    webhook_url = (feishu_binding.get("webhook_url") or "").strip()
    if not webhook_url:
        logger.warning("Feishu webhook configuration missing, skip sending.")
        return
    if not (options["include_brief"] or options["include_weather"] or options["include_typhoon"]):
        logger.info("Feishu delivery content is fully disabled, skip sending.")
        return

    card = build_feishu_weather_brief_card(
        weather_report=weather_report,
        brief_title=brief_title,
        brief_topic=brief_topic,
        brief_date=brief_date,
        brief_url=brief_url,
        include_brief=options["include_brief"],
        include_weather=options["include_weather"],
        include_typhoon=options["include_typhoon"],
    )
    try:
        send_feishu_webhook_card(webhook_url, card)
    except Exception as exc:
        logger.error("Failed to send Feishu robot card: %s", exc)
