import smtplib  # 导入 SMTP 协议库用于发邮件
from email.mime.text import MIMEText  # 导入邮件文本构建类
from email.mime.multipart import MIMEMultipart  # 导入复合邮件类
import requests  # 导入 requests 发送 HTTP 请求
import logging  # 导入日志
from datetime import date  # 导入 date
from app.config import settings  # 导入配置

logger = logging.getLogger(__name__)  # 初始化日志

def send_email(html_content: str, brief_date: date):  # 定义邮件推送函数
    if not settings.EMAIL_SENDER or not settings.EMAIL_PASSWORD:  # 检查邮箱配置是否齐全
        logger.warning("Email configuration missing, skip sending.")  # 若缺失则警告并跳过
        return
        
    receivers = settings.email_receivers_list  # 获取收件人列表
    if not receivers:  # 如果收件人为空
        return  # 跳过
        
    msg = MIMEMultipart()  # 实例化复合邮件对象
    msg['From'] = settings.EMAIL_SENDER  # 设置发件人
    msg['To'] = ", ".join(receivers)  # 设置收件人字符串
    msg['Subject'] = f"IntelliBrief 每日简报 - {brief_date.strftime('%Y-%m-%d')}"  # 设置邮件主题
    
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))  # 将渲染好的 HTML 作为邮件正文附加
    
    try:
        # 这里以 QQ 邮箱的 SMTP 服务器为例，实际可根据配置更改主机和端口
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)  # 建立 SSL 连接
        server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)  # 登录发件邮箱
        server.sendmail(settings.EMAIL_SENDER, receivers, msg.as_string())  # 发送邮件
        server.quit()  # 退出 SMTP 服务器
        logger.info(f"Brief email sent for {brief_date}")  # 记录成功日志
    except Exception as e:
        logger.error(f"Failed to send email: {e}")  # 记录异常日志

def send_webhook(brief_url: str):  # 定义 Webhook 推送函数（以飞书为例）
    if not settings.FEISHU_WEBHOOK:  # 检查飞书 Webhook 是否配置
        logger.warning("Feishu webhook not configured, skip sending.")  # 缺失则跳过
        return
        
    # 构建飞书机器人富文本消息结构体 (Post 类型)
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "📰 IntelliBrief 每日简报已生成",
                    "content": [
                        [
                            {
                                "tag": "text",
                                "text": "今日的情报简报已经准备好啦，点击下方链接查看详情："
                            },
                            {
                                "tag": "a",
                                "text": "查看简报",
                                "href": brief_url
                            }
                        ]
                    ]
                }
            }
        }
    }
    
    try:
        resp = requests.post(settings.FEISHU_WEBHOOK, json=payload, timeout=10)  # 发送 POST 请求到 Webhook 地址
        resp.raise_for_status()  # 检查 HTTP 状态码
        logger.info("Feishu webhook sent.")  # 记录成功日志
    except Exception as e:
        logger.error(f"Failed to send webhook: {e}")  # 记录失败日志
