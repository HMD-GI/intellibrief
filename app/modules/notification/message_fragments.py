import html
import re


def normalize_receivers(value) -> list[str]:
    """将前端保存的收件人统一转成字符串数组。"""

    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def render_weather_lines(weather_report: dict | None) -> list[str]:
    """生成天气摘要文本。"""

    if not weather_report:
        return []

    summary = weather_report.get("weather_summary") or {}
    provider = weather_report.get("provider") or {}
    hourly = weather_report.get("hourly") or []
    notices = weather_report.get("notices") or []

    preview_hours: list[str] = []
    for item in hourly[:6]:
        time_label = (item.get("fxTime") or "")[11:16]
        preview_hours.append(f"{time_label} {item.get('text', '-')}/{item.get('temp', '-')}°C")

    lines = [
        f"地区：{weather_report.get('region') or '-'}",
        f"日期：{weather_report.get('date') or '-'}",
        f"数据源：{provider.get('label', '-')}",
        f"气温范围：{summary.get('temp_min', '-')}°C ~ {summary.get('temp_max', '-')}°C",
    ]
    if preview_hours:
        lines.append("分时预报：" + "；".join(preview_hours))
    for notice in notices[:2]:
        lines.append("说明：" + str(notice))
    return lines


def render_typhoon_lines(weather_report: dict | None) -> list[str]:
    """生成台风摘要文本。"""

    if not weather_report:
        return []

    typhoon = weather_report.get("typhoon") or {}
    alerts = typhoon.get("alerts") or []
    active = typhoon.get("active") or []

    lines = [typhoon.get("summary") or "当前未查询到台风预警或台风活动。"]
    if alerts:
        alert_titles = [item.get("title") for item in alerts if item.get("title")]
        if alert_titles:
            lines.append("台风预警：" + "；".join(alert_titles[:3]))

    for item in active[:2]:
        forecast = item.get("forecast") or []
        forecast_text = "；".join(
            f"{entry.get('fxTime', '-')}：{entry.get('text', '-')}" for entry in forecast[:3]
        )
        line = (
            f"{item.get('name', '台风')}，风速 {item.get('windSpeed', '-')}，"
            f"气压 {item.get('pressure', '-')}，移动方向 {item.get('moveDir', '-')}"
        )
        if forecast_text:
            line += f"，未来预测：{forecast_text}"
        lines.append(line)

    return lines


def build_html_list(lines: list[str]) -> str:
    """将纯文本行转成简单的 HTML 段落。"""

    return "".join(f"<p style='margin:6px 0;'>{html.escape(line)}</p>" for line in lines if line)


def extract_html_body(brief_html: str | None) -> str:
    """提取简报 HTML 的 body 内容。"""

    if not brief_html:
        return ""
    match = re.search(r"<body[^>]*>(.*)</body>", brief_html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else brief_html
