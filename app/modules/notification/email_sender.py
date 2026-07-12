import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.modules.notification.binding_store import channel_options, load_binding_settings
from app.modules.notification.message_fragments import (
    build_html_list,
    extract_html_body,
    normalize_receivers,
    render_typhoon_lines,
    render_weather_lines,
)

logger = logging.getLogger(__name__)


def _build_email_body(
    brief_html: str | None,
    weather_report: dict | None,
    include_brief: bool,
    include_weather: bool,
    include_typhoon: bool,
) -> str:
    """构建邮件正文。

    技术原理：
    1. 邮件中分成“简报模块”和“天气模块”两个独立区块。
    2. 天气、台风只在发送阶段拼接，不写回简报 HTML。
    """

    sections: list[str] = []

    if include_brief and brief_html:
        sections.append(
            "<section style='margin-bottom:24px;'>"
            "<h2 style='margin:0 0 12px;font-size:18px;'>简报内容</h2>"
            f"{extract_html_body(brief_html)}"
            "</section>"
        )

    weather_sections: list[str] = []
    if include_weather:
        weather_lines = render_weather_lines(weather_report)
        if weather_lines:
            weather_sections.append(
                "<div style='margin-bottom:16px;'>"
                "<h3 style='margin:0 0 10px;font-size:16px;'>天气情况</h3>"
                f"{build_html_list(weather_lines)}"
                "</div>"
            )
    if include_typhoon:
        typhoon_lines = render_typhoon_lines(weather_report)
        if typhoon_lines:
            weather_sections.append(
                "<div>"
                "<h3 style='margin:0 0 10px;font-size:16px;'>台风情况</h3>"
                f"{build_html_list(typhoon_lines)}"
                "</div>"
            )
    if weather_sections:
        sections.append(
            "<section style='margin-top:24px;padding:16px;border:1px solid #e5e8ef;border-radius:8px;'>"
            "<h2 style='margin:0 0 12px;font-size:18px;'>天气模块</h2>"
            + "".join(weather_sections)
            + "</section>"
        )

    if not sections:
        sections.append("<p>当前未配置任何发送内容。</p>")
    return "<html><body>" + "".join(sections) + "</body></html>"


def send_email(
    brief_html: str | None,
    brief_date: date,
    brief_title: str | None = None,
    weather_report: dict | None = None,
) -> None:
    """发送邮件。"""

    bindings = load_binding_settings()
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
    if not (options["include_brief"] or options["include_weather"] or options["include_typhoon"]):
        logger.info("Email delivery content is fully disabled, skip sending.")
        return

    final_html = _build_email_body(
        brief_html=brief_html,
        weather_report=weather_report,
        include_brief=options["include_brief"],
        include_weather=options["include_weather"],
        include_typhoon=options["include_typhoon"],
    )
    subject = brief_title or f"IntelliBrief 每日简报 - {brief_date.strftime('%Y-%m-%d')}"

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
        logger.info("Brief email sent for %s", brief_date)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
