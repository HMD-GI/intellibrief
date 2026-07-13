import logging
from datetime import date, datetime
from typing import Any

import requests

from app.modules.notification.message_fragments import (
    render_brief_markdown_lines,
    render_typhoon_lines,
    render_update_time_line,
    render_weather_lines,
)

logger = logging.getLogger(__name__)


def _safe_text(value: Any, default: str = "-") -> str:
    """把任意值规整为安全文本。"""

    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _build_markdown_section(title: str, lines: list[str]) -> dict[str, Any]:
    """构造一个飞书 markdown 区块。"""

    content = f"**{title}**\n" + ("\n".join(lines) if lines else "暂无数据")
    return {"tag": "markdown", "content": content}


def build_feishu_weather_brief_card(
    *,
    weather_report: dict[str, Any] | None,
    briefs: list[dict[str, Any]] | None = None,
    brief_title: str | None = None,
    brief_topic: str | None = None,
    brief_date: date | None = None,
    brief_url: str | None = None,
    include_brief: bool,
    include_weather: bool,
    include_typhoon: bool,
) -> dict[str, Any]:
    """构造飞书机器人卡片消息。"""

    normalized_briefs = briefs or []
    if not normalized_briefs and brief_date is not None:
        normalized_briefs = [
            {
                "title": brief_title,
                "topic": brief_topic,
                "date": brief_date.strftime("%Y-%m-%d"),
                "url": brief_url,
            }
        ]

    today_label = brief_date.strftime("%Y-%m-%d") if brief_date else datetime.now().strftime("%Y-%m-%d")
    region = _safe_text((weather_report or {}).get("region"))
    report_date = _safe_text((weather_report or {}).get("date"), today_label)
    provider = _safe_text(((weather_report or {}).get("provider") or {}).get("label"))
    summary = (weather_report or {}).get("weather_summary") or {}
    temp_min = _safe_text(summary.get("temp_min"))
    temp_max = _safe_text(summary.get("temp_max"))

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**地区**\n{region}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{report_date}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**天气源**\n{provider}"}},
                {
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": f"**气温范围**\n{temp_min}°C ~ {temp_max}°C"},
                },
            ],
        }
    ]

    if include_weather:
        elements.append({"tag": "hr"})
        elements.append(_build_markdown_section("全天分时天气", render_weather_lines(weather_report)))

    if include_typhoon:
        elements.append({"tag": "hr"})
        elements.append(_build_markdown_section("台风情况", render_typhoon_lines(weather_report)))

    if include_brief:
        elements.append({"tag": "hr"})
        elements.append(_build_markdown_section("发送简报", render_brief_markdown_lines(normalized_briefs)))

    elements.append(
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": render_update_time_line()}],
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{region} 天气与简报播报"},
            "template": "blue",
        },
        "elements": elements,
    }


def send_feishu_webhook_card(webhook_url: str, card: dict[str, Any]) -> None:
    """通过飞书机器人 Webhook 发送卡片消息。"""

    response = requests.post(
        webhook_url.strip(),
        json={"msg_type": "interactive", "card": card},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    code = payload.get("code", payload.get("StatusCode", payload.get("statusCode", 0)))
    if code not in (0, "0"):
        raise RuntimeError(payload.get("msg") or payload.get("StatusMessage") or "Feishu webhook send failed")
    logger.info("Feishu webhook card sent.")
