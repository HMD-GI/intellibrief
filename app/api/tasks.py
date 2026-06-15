import logging  # 导入日志模块
from fastapi import APIRouter, Depends, BackgroundTasks  # 导入 APIRouter 等组件
from pydantic import BaseModel  # 导入请求体模型
from sqlalchemy.orm import Session  # 导入数据库会话类型
import json  # 导入 JSON
from app.api.response import ok  # 导入统一响应函数
from app.database import get_db  # 导入数据库依赖
from app.models.setting import AppSetting  # 导入设置模型
from app.models.source import Source  # 导入信息源模型
from scheduler.tasks import crawl_all_sources, ai_process_articles, generate_and_push_brief, run_all_tasks_immediately  # 导入 Celery 任务函数

router = APIRouter(prefix="/tasks", tags=["tasks"])  # 创建任务管理路由实例，前缀 /tasks
logger = logging.getLogger(__name__)  # 初始化日志记录器


def _submit_task(task, background_tasks: BackgroundTasks, *args, **kwargs):  # 提交 Celery 任务，失败时降级为本进程后台任务
    try:
        task.delay(*args, **kwargs)  # 优先使用 Celery 队列，保证生产环境异步执行
        return "queued"
    except Exception as exc:
        logger.warning("Celery task submit failed, fallback to FastAPI background task: %s", exc)
        background_tasks.add_task(task, *args, **kwargs)  # Celery 不可用时避免前端接口直接 500
        return "background"


class GenerateBriefRequest(BaseModel):  # 定义一键生成请求体
    topics: list[str] = []  # 前端选择的主题
    send_email: bool = False  # 是否发送邮箱
    send_feishu: bool = False  # 是否发送飞书


class ScheduleRequest(BaseModel):  # 定义定时生成请求体
    time: str  # HH:mm 格式时间
    topics: list[str] = []  # 定时生成主题
    enabled: bool = True  # 是否启用

@router.post("/crawl")  # 注册触发全量爬虫的 POST 路由
def trigger_crawl(background_tasks: BackgroundTasks):  # 处理函数
    mode = _submit_task(crawl_all_sources, background_tasks, process_inline=True)  # 抓取详情页日期为当天的全部文章并同步入库
    return ok({"submitted": True, "mode": mode}, "Crawl task triggered")  # 返回触发成功消息

@router.post("/ai-process")  # 注册触发 AI 处理流程的 POST 路由
def trigger_ai_process(background_tasks: BackgroundTasks):  # 处理函数
    mode = _submit_task(ai_process_articles, background_tasks)  # 异步调用 AI 处理任务
    return ok({"submitted": True, "mode": mode}, "AI process task triggered")  # 返回触发成功消息

@router.post("/generate-brief")  # 注册触发生成简报的 POST 路由
def trigger_generate_brief(background_tasks: BackgroundTasks, payload: GenerateBriefRequest | None = None, db: Session = Depends(get_db)):  # 处理函数
    if payload:
        row = db.query(AppSetting).filter(AppSetting.key == "last_generate_options").first()
        value = json.dumps(payload.model_dump(), ensure_ascii=False)
        if not row:
            row = AppSetting(key="last_generate_options", value=value)
            db.add(row)
        else:
            row.value = value
        if payload.topics:
            topic_text = ",".join(payload.topics)
            for source in db.query(Source).filter(Source.is_active == True).all():
                source.topics = topic_text  # 将前端选择主题同步到激活信息源
        db.commit()
    mode = _submit_task(run_all_tasks_immediately, background_tasks)  # 异步调用完整流水线生成当日简报
    return ok({"submitted": True, "mode": mode}, "Generate brief task triggered")  # 返回触发成功消息


@router.post("/schedule")  # 注册保存定时生成配置接口
def save_schedule(payload: ScheduleRequest, db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
    value = json.dumps(payload.model_dump(), ensure_ascii=False)
    if not row:
        row = AppSetting(key="schedule", value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return ok(payload.model_dump(), "schedule saved")

@router.post("/run-all")  # 注册触发完整流水线的 POST 路由
def trigger_run_all(background_tasks: BackgroundTasks):  # 处理函数
    """
    一键触发完整的流水线（测试用）：爬取 -> AI分析 -> 生成简报
    """
    mode = _submit_task(run_all_tasks_immediately, background_tasks)  # 异步调用全流程任务
    return ok({"submitted": True, "mode": mode}, "Full pipeline task triggered immediately")  # 返回触发成功消息
