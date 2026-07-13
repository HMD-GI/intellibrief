import logging
import time
from datetime import date

from app.modules.notification.binding_store import channel_options, load_binding_settings
from app.modules.notification.feishu_card import (
    build_feishu_weather_brief_card,
    send_feishu_webhook_card,
)

logger = logging.getLogger(__name__)


def _normalize_feishu_error(exc: Exception) -> RuntimeError:
    """把飞书发送异常转换成更清晰的错误。"""

    message = str(exc).strip() or "Feishu send failed"
    if "frequency limited" in message.lower():
        return RuntimeError("飞书机器人触发频率限制，请稍后重试。")
    return RuntimeError(f"飞书发送失败：{message}")


def send_feishu_robot_card(
    brief_url: str | None = None,
    brief_title: str | None = None,
    brief_topic: str | None = None,
    brief_date: date | None = None,
    weather_report: dict | None = None,
    user_key: str | None = None,
    briefs: list[dict] | None = None,
) -> None:
    """通过飞书机器人发送卡片消息。

    技术说明：
    1. 发送配置按 user_key 从数据库读取，实现不同用户各自的 Webhook 隔离。
    2. 新增 briefs 参数后，可以把多份简报合并到一条飞书消息中发送。
    3. 保留单份简报参数，兼容旧调用点。
    """

    bindings = load_binding_settings(user_key=user_key)
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
        briefs=briefs,
        brief_title=brief_title,
        brief_topic=brief_topic,
        brief_date=brief_date,
        brief_url=brief_url,
        include_brief=options["include_brief"],
        include_weather=options["include_weather"],
        include_typhoon=options["include_typhoon"],
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            send_feishu_webhook_card(webhook_url, card)
            return
        except Exception as exc:
            last_exc = exc
            normalized = _normalize_feishu_error(exc)
            logger.error("Failed to send Feishu robot card: %s", normalized)
            if "频率限制" not in str(normalized) or attempt == 2:
                raise normalized
            time.sleep(1.5 * (attempt + 1))
    if last_exc:
        raise _normalize_feishu_error(last_exc)
