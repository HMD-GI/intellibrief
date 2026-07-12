import logging
from datetime import date, datetime

import requests

logger = logging.getLogger(__name__)


def _weather_emoji(text: str | None) -> str:
    """根据天气文案返回简洁图标。"""

    content = (text or "").strip()
    if any(keyword in content for keyword in ("雷", "暴")):
        return "⛈️"
    if "雪" in content:
        return "❄️"
    if "雨" in content:
        return "🌧️"
    if "雾" in content:
        return "🌫️"
    if "阴" in content:
        return "☁️"
    if any(keyword in content for keyword in ("云", "多云")):
        return "⛅"
    if "晴" in content:
        return "☀️"
    return "🌤️"


def _safe_text(value) -> str:
    """将任意值转成飞书卡片安全文本。"""

    if value is None:
        return "-"
    return str(value).strip() or "-"


def _build_hourly_lines(weather_report: dict | None) -> list[str]:
    """构造全天分时天气文本。"""

    if not weather_report:
        return []

    lines: list[str] = []
    for item in weather_report.get("hourly") or []:
        fx_time = _safe_text(item.get("fxTime"))
        time_label = fx_time[11:16] if len(fx_time) >= 16 else fx_time
        weather_text = _safe_text(item.get("text"))
        emoji = _weather_emoji(weather_text)
        line = (
            f"{time_label} {emoji} {weather_text} | "
            f"{_safe_text(item.get('temp'))}°C | "
            f"降雨 {_safe_text(item.get('pop'))}% | "
            f"湿度 {_safe_text(item.get('humidity'))}%"
        )
        lines.append(line)
    return lines


def _build_typhoon_lines(weather_report: dict | None) -> list[str]:
    """构造台风信息文本。"""

    if not weather_report:
        return []

    typhoon = weather_report.get("typhoon") or {}
    warnings = weather_report.get("warnings") or []
    lines: list[str] = [f"🌀 {_safe_text(typhoon.get('summary'))}"]

    for warning in warnings[:3]:
        lines.append(
            f"⚠️ {_safe_text(warning.get('title'))}：{_safe_text(warning.get('text'))}"
        )

    for item in (typhoon.get("active") or [])[:2]:
        lines.append(
            f"🌀 {_safe_text(item.get('name'))} | 强度 {_safe_text(item.get('level'))} | "
            f"风速 {_safe_text(item.get('windSpeed'))} | 气压 {_safe_text(item.get('pressure'))} | "
            f"移动 {_safe_text(item.get('moveDir'))}"
        )
        for forecast in (item.get("forecast") or [])[:4]:
            lines.append(
                f"   ↳ {_safe_text(forecast.get('fxTime'))} {_safe_text(forecast.get('text'))}"
            )
    return lines


def _build_brief_lines(
    brief_title: str | None,
    brief_topic: str | None,
    brief_date: date,
    brief_url: str | None,
) -> list[str]:
    """构造简报说明文本。"""

    return [
        f"📌 标题：{_safe_text(brief_title)}",
        f"🗂️ 主题：{_safe_text(brief_topic or '综合')}",
        f"📅 日期：{brief_date.strftime('%Y-%m-%d')}",
        f"🔗 链接：[查看简报]({_safe_text(brief_url)})" if brief_url else "🔗 链接：未提供",
    ]


def _build_markdown_section(title: str, lines: list[str]) -> dict:
    """构造一个 markdown 卡片区块。"""

    content = f"**{title}**\n" + ("\n".join(lines) if lines else "暂无数据")
    return {
        "tag": "markdown",
        "content": content,
    }


def build_feishu_weather_brief_card(
    *,
    weather_report: dict | None,
    brief_title: str | None,
    brief_topic: str | None,
    brief_date: date,
    brief_url: str | None,
    include_brief: bool,
    include_weather: bool,
    include_typhoon: bool,
) -> dict:
    """构造飞书机器人卡片消息。"""

    region = _safe_text((weather_report or {}).get("region"))
    report_date = _safe_text((weather_report or {}).get("date") or brief_date.strftime("%Y-%m-%d"))
    provider = _safe_text(((weather_report or {}).get("provider") or {}).get("label"))
    summary = (weather_report or {}).get("weather_summary") or {}
    temp_min = _safe_text(summary.get("temp_min"))
    temp_max = _safe_text(summary.get("temp_max"))
    notices = (weather_report or {}).get("notices") or []

    header_title = f"{region} 天气与简报播报"
    elements: list[dict] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**地区**\n{region}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{report_date}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**天气源**\n{provider}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**气温范围**\n{temp_min}°C ~ {temp_max}°C"}},
            ],
        }
    ]

    if include_weather:
        elements.append({"tag": "hr"})
        elements.append(_build_markdown_section("全天分时天气", _build_hourly_lines(weather_report)))

    if include_typhoon:
        elements.append({"tag": "hr"})
        elements.append(_build_markdown_section("台风情况", _build_typhoon_lines(weather_report)))

    if include_brief:
        elements.append({"tag": "hr"})
        elements.append(
            _build_markdown_section(
                "发送简报",
                _build_brief_lines(brief_title, brief_topic, brief_date, brief_url),
            )
        )

    note_text = f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if notices:
        note_text += " | " + "；".join(_safe_text(item) for item in notices[:2])

    elements.append(
        {
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": note_text},
            ],
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "blue",
        },
        "elements": elements,
    }


def send_feishu_webhook_card(webhook_url: str, card: dict) -> None:
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
