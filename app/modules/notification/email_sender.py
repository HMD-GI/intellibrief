import logging
import smtplib
from datetime import date
from email.utils import parseaddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.config import settings
from app.modules.notification.binding_store import channel_options, load_binding_settings
from app.modules.notification.message_fragments import (
    build_html_brief_list,
    build_html_list,
    normalize_receivers,
    render_typhoon_lines,
    render_update_time_line,
    render_weather_lines,
)

logger = logging.getLogger(__name__)


def _safe_text(value: Any, default: str = "-") -> str:
    """把任意值规整成安全文本。"""

    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _validate_email_address(address: str) -> bool:
    """校验邮箱地址是否符合最基本格式。"""

    _, parsed = parseaddr((address or "").strip())
    return bool(parsed and "@" in parsed and "." in parsed.split("@", 1)[-1])


def _build_email_body(
    briefs: list[dict[str, Any]] | None,
    weather_report: dict[str, Any] | None,
    include_brief: bool,
    include_weather: bool,
    include_typhoon: bool,
) -> str:
    """构建与飞书播报结构一致的邮件正文。"""

    region = _safe_text((weather_report or {}).get("region"))
    report_date = _safe_text((weather_report or {}).get("date"))
    provider = _safe_text(((weather_report or {}).get("provider") or {}).get("label"))
    summary = (weather_report or {}).get("weather_summary") or {}
    temp_min = _safe_text(summary.get("temp_min"))
    temp_max = _safe_text(summary.get("temp_max"))

    sections: list[str] = [
        "<section style='margin-bottom:20px;'>"
        f"<h1 style='margin:0 0 12px;font-size:22px;'>{region} 天气与简报播报</h1>"
        f"<p style='margin:6px 0;'><strong>地区</strong><br>{region}</p>"
        f"<p style='margin:6px 0;'><strong>日期</strong><br>{report_date}</p>"
        f"<p style='margin:6px 0;'><strong>天气源</strong><br>{provider}</p>"
        f"<p style='margin:6px 0;'><strong>气温范围</strong><br>{temp_min}°C ~ {temp_max}°C</p>"
        "</section>"
    ]

    if include_weather:
        weather_lines = render_weather_lines(weather_report)
        sections.append(
            "<section style='margin-bottom:20px;'>"
            "<h2 style='margin:0 0 10px;font-size:18px;'>全天分时天气</h2>"
            f"{build_html_list(weather_lines)}"
            "</section>"
        )

    if include_typhoon:
        typhoon_lines = render_typhoon_lines(weather_report)
        sections.append(
            "<section style='margin-bottom:20px;'>"
            "<h2 style='margin:0 0 10px;font-size:18px;'>台风情况</h2>"
            f"{build_html_list(typhoon_lines)}"
            "</section>"
        )

    if include_brief:
        sections.append(
            "<section style='margin-bottom:20px;'>"
            "<h2 style='margin:0 0 10px;font-size:18px;'>发送简报</h2>"
            f"{build_html_brief_list(briefs)}"
            "</section>"
        )

    sections.append(
        "<section style='margin-top:20px;color:#666;'>"
        f"<p style='margin:6px 0;'>{render_update_time_line()}</p>"
        "</section>"
    )
    return "<html><body style='font-family:Segoe UI,PingFang SC,Microsoft YaHei,sans-serif;'>" + "".join(sections) + "</body></html>"


def send_email(
    brief_html: str | None = None,
    brief_date: date | None = None,
    brief_title: str | None = None,
    weather_report: dict[str, Any] | None = None,
    user_key: str | None = None,
    briefs: list[dict[str, Any]] | None = None,
) -> None:
    """发送邮件。"""

    bindings = load_binding_settings(user_key=user_key)
    email_binding = bindings.get("email", {})
    options = channel_options(email_binding)
    sender = email_binding.get("sender") or settings.EMAIL_SENDER
    password = email_binding.get("password") or settings.EMAIL_PASSWORD
    receivers = normalize_receivers(email_binding.get("receivers") or settings.email_receivers_list)
    smtp_host = email_binding.get("smtp_host") or settings.EMAIL_SMTP_HOST
    smtp_port = int(email_binding.get("smtp_port") or settings.EMAIL_SMTP_PORT)
    smtp_use_ssl = email_binding.get("smtp_use_ssl", settings.EMAIL_SMTP_USE_SSL)
    if isinstance(smtp_use_ssl, str):
        smtp_use_ssl = smtp_use_ssl.lower() in {"1", "true", "yes", "on"}

    if not sender or not password or not smtp_host or not receivers:
        logger.warning("Email configuration missing, skip sending.")
        return
    if not _validate_email_address(sender):
        raise RuntimeError(f"邮箱发件人地址无效：{sender}")
    invalid_receivers = [receiver for receiver in receivers if not _validate_email_address(receiver)]
    if invalid_receivers:
        raise RuntimeError(f"邮箱收件人地址无效：{', '.join(invalid_receivers)}")
    if not (options["include_brief"] or options["include_weather"] or options["include_typhoon"]):
        logger.info("Email delivery content is fully disabled, skip sending.")
        return

    normalized_briefs = briefs or []
    if not normalized_briefs and brief_date is not None:
        normalized_briefs = [
            {
                "title": brief_title,
                "topic": None,
                "date": brief_date.strftime("%Y-%m-%d"),
                "url": None,
            }
        ]

    final_html = _build_email_body(
        briefs=normalized_briefs,
        weather_report=weather_report,
        include_brief=options["include_brief"],
        include_weather=options["include_weather"],
        include_typhoon=options["include_typhoon"],
    )
    subject_date = (weather_report or {}).get("date") or (brief_date or date.today()).strftime("%Y-%m-%d")
    region = _safe_text((weather_report or {}).get("region"), "IntelliBrief")
    subject = f"{region} 天气与简报播报 - {subject_date}"

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = ", ".join(receivers)
    message["Subject"] = subject
    message.attach(MIMEText(final_html, "html", "utf-8"))

    try:
        if smtp_use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receivers, message.as_string())
        server.quit()
        logger.info("Brief email sent for %s", subject_date)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        raise RuntimeError(f"邮箱发送失败：{exc}") from exc
