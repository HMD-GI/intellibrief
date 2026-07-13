import html
import re
from datetime import datetime
from typing import Any


def _current_typhoon_point(item: dict[str, Any]) -> dict[str, Any]:
    """提取通知里需要发送的当前台风点位。"""

    return item.get("current_point") or ((item.get("track") or [])[-1] if item.get("track") else {}) or {}


def _safe_text(value: Any, default: str = "-") -> str:
    """把任意值规整成可显示文本。"""

    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _weather_emoji(text: str | None) -> str:
    """根据天气文案返回一个轻量图标。"""

    value = text or ""
    if "雷" in value:
        return "⛈️"
    if "暴雨" in value or "大雨" in value or "中雨" in value or "小雨" in value or "雨" in value:
        return "🌧️"
    if "雪" in value:
        return "❄️"
    if "阴" in value:
        return "☁️"
    if "多云" in value:
        return "⛅"
    if "晴" in value:
        return "☀️"
    if "雾" in value or "霾" in value:
        return "🌫️"
    return "🌤️"


def normalize_receivers(value: Any) -> list[str]:
    """把收件人配置统一转换为字符串数组。"""

    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def render_weather_lines(weather_report: dict[str, Any] | None) -> list[str]:
    """生成与旧播报格式一致的天气文本。"""

    if not weather_report:
        return []

    lines: list[str] = []
    for item in weather_report.get("hourly") or []:
        fx_time = _safe_text(item.get("fxTime"), "")
        time_label = fx_time[11:16] if len(fx_time) >= 16 else fx_time or "--:--"
        text = _safe_text(item.get("text"))
        temp = _safe_text(item.get("temp"))
        pop = _safe_text(item.get("pop"))
        humidity = _safe_text(item.get("humidity"))
        lines.append(
            f"{time_label} {_weather_emoji(text)} {text} | {temp}°C | 降雨 {pop}% | 湿度 {humidity}%"
        )
    return lines


def render_typhoon_lines(weather_report: dict[str, Any] | None) -> list[str]:
    """生成台风播报文本，只发送当前点位详情。"""

    if not weather_report:
        return []

    typhoon = weather_report.get("typhoon") or {}
    alerts = typhoon.get("alerts") or []
    active = typhoon.get("active") or []

    lines = [_safe_text(typhoon.get("summary"), "当前未查询到台风活动。")]
    if alerts:
        alert_titles = [item.get("title") for item in alerts if item.get("title")]
        if alert_titles:
            lines.append("⚠️ 台风预警：" + "；".join(alert_titles[:3]))

    for item in active:
        point = _current_typhoon_point(item)
        lines.append(
            "🌀 "
            f"{_safe_text(item.get('name'), '台风')} | "
            f"时间 {_safe_text(point.get('fxTime'))} | "
            f"位置 {_safe_text(point.get('lat'))}, {_safe_text(point.get('lon'))} | "
            f"风速 {_safe_text(point.get('windSpeed'))} | "
            f"气压 {_safe_text(point.get('pressure'))} | "
            f"描述 {_safe_text(point.get('text'))}"
        )
    return lines


def render_brief_lines(briefs: list[dict[str, Any]] | None) -> list[str]:
    """生成多份简报的摘要文本。"""

    lines: list[str] = []
    for index, brief in enumerate(briefs or []):
        if index > 0:
            lines.append("")
        lines.extend(
            [
                f"📌 标题：{_safe_text(brief.get('title'))}",
                f"🗂️ 主题：{_safe_text(brief.get('topic'), '综合')}",
                f"📅 日期：{_safe_text(brief.get('date'))}",
                "🔗 链接：查看简报",
            ]
        )
    return lines


def render_brief_markdown_lines(briefs: list[dict[str, Any]] | None) -> list[str]:
    """生成适用于飞书 markdown 的简报文本。"""

    lines: list[str] = []
    for index, brief in enumerate(briefs or []):
        if index > 0:
            lines.append("")
        url = _safe_text(brief.get("url"), "")
        link_text = f"[查看简报]({url})" if url else "查看简报"
        lines.extend(
            [
                f"📌 标题：{_safe_text(brief.get('title'))}",
                f"🗂️ 主题：{_safe_text(brief.get('topic'), '综合')}",
                f"📅 日期：{_safe_text(brief.get('date'))}",
                f"🔗 链接：{link_text}",
            ]
        )
    return lines


def build_html_list(lines: list[str]) -> str:
    """把文本行转换为简单 HTML 段落。"""

    html_lines: list[str] = []
    for line in lines:
        if line == "":
            html_lines.append("<div style='height:10px;'></div>")
        else:
            html_lines.append(f"<p style='margin:6px 0;'>{html.escape(line)}</p>")
    return "".join(html_lines)


def build_html_brief_list(briefs: list[dict[str, Any]] | None) -> str:
    """把多份简报生成带可点击链接的 HTML。"""

    html_lines: list[str] = []
    for index, brief in enumerate(briefs or []):
        if index > 0:
            html_lines.append("<div style='height:10px;'></div>")
        title_line = f"📌 标题：{_safe_text(brief.get('title'))}"
        topic_line = f"🗂️ 主题：{_safe_text(brief.get('topic'), '综合')}"
        date_line = f"📅 日期：{_safe_text(brief.get('date'))}"
        html_lines.append(f"<p style='margin:6px 0;'>{html.escape(title_line)}</p>")
        html_lines.append(f"<p style='margin:6px 0;'>{html.escape(topic_line)}</p>")
        html_lines.append(f"<p style='margin:6px 0;'>{html.escape(date_line)}</p>")
        url = _safe_text(brief.get("url"), "")
        if url:
            html_lines.append(
                "<p style='margin:6px 0;'>🔗 链接："
                f"<a href=\"{html.escape(url, quote=True)}\" target=\"_blank\" rel=\"noopener noreferrer\">查看简报</a>"
                "</p>"
            )
        else:
            html_lines.append("<p style='margin:6px 0;'>🔗 链接：查看简报</p>")
    return "".join(html_lines)


def extract_html_body(brief_html: str | None) -> str:
    """提取 HTML 的 body 内容。"""

    if not brief_html:
        return ""
    match = re.search(r"<body[^>]*>(.*)</body>", brief_html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else brief_html


def render_update_time_line() -> str:
    """生成统一更新时间文案。"""

    return f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
