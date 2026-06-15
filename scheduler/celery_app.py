from celery import Celery  # 导入 Celery 类
from app.config import settings  # 导入配置
import os  # 导入系统模块

# 设置默认的 Celery 配置模块环境变量 (兼容标准做法)
os.environ.setdefault('CELERY_CONFIG_MODULE', 'scheduler.periodic')

celery_app = Celery(  # 实例化 Celery 对象
    "intellibrief",  # 项目名称
    broker=settings.REDIS_URL,  # 消息代理 (Broker) 使用 Redis
    backend=settings.REDIS_URL,  # 结果存储后端 (Backend) 也使用 Redis
    include=['scheduler.tasks']  # 包含的任务模块路径
)

celery_app.conf.update(  # 更新 Celery 配置
    task_serializer='json',  # 任务序列化格式为 JSON
    accept_content=['json'],  # 接受的内容类型为 JSON
    result_serializer='json',  # 结果序列化格式为 JSON
    timezone='Asia/Shanghai',  # 设置时区为亚洲/上海
    enable_utc=True,  # 开启 UTC
)

# 加载定时任务配置
celery_app.config_from_object('scheduler.periodic')
