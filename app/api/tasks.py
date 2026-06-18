import json  # 导入 JSON 模块，用于保存配置
import logging  # 导入日志模块
import threading  # 导入线程模块，用于本进程定时生成
from datetime import datetime, timedelta  # 导入时间计算工具

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException  # 导入 FastAPI 路由和异常组件
from pydantic import BaseModel  # 导入请求体模型
from sqlalchemy.orm import Session  # 导入数据库会话类型

from app.api.response import ok  # 导入统一响应函数
from app.database import SessionLocal, get_db  # 导入数据库依赖
from app.models.setting import AppSetting  # 导入设置模型
from scheduler.tasks import ai_process_articles, crawl_all_sources, run_all_tasks_immediately  # 导入流水线任务

router = APIRouter(prefix="/tasks", tags=["tasks"])  # 创建任务路由实例
logger = logging.getLogger(__name__)  # 初始化日志记录器
_schedule_timer: threading.Timer | None = None  # 保存当前定时器实例
_schedule_lock = threading.Lock()  # 保护定时器状态，避免并发重复启动


class GenerateBriefRequest(BaseModel):  # 一键生成请求体
    topics: list[str] = []  # 前端选择的主题列表
    keywords: list[str] = []  # 前端输入的关键词数组
    send_email: bool = False  # 是否发送邮件
    send_feishu: bool = False  # 是否发送飞书


class ScheduleRequest(BaseModel):  # 定时生成请求体
    time: str  # HH:mm 格式时间
    topics: list[str] = []  # 定时生成主题列表
    keywords: list[str] = []  # 定时生成关键词数组
    enabled: bool = True  # 是否启用定时任务


def _normalize_topics(topics: list[str] | None) -> list[str]:  # 规整主题列表
    return [topic.strip() for topic in (topics or []) if topic and topic.strip()]  # 去掉空值和首尾空白


def _normalize_keywords(keywords: list[str] | None) -> list[str]:  # 规整关键词列表
    return [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]  # 去掉空值和首尾空白


def _upsert_setting(db: Session, key: str, value_dict: dict) -> None:  # 保存通用设置
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = json.dumps(value_dict, ensure_ascii=False)  # 以中文 JSON 保存配置
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _seconds_until_run(time_text: str) -> float:  # 计算距离下一次运行的秒数
    hour, minute = [int(part) for part in time_text.split(":", 1)]
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)  # 当天时间已过则顺延到明天
    return max(1.0, (next_run - now).total_seconds())


def _cancel_schedule_timer() -> None:  # 取消当前定时器
    global _schedule_timer
    with _schedule_lock:
        if _schedule_timer:
            _schedule_timer.cancel()
            _schedule_timer = None


def _run_scheduled_brief(topics: list[str], time_text: str, keywords: list[str] | None = None) -> None:  # 定时触发完整流水线
    logger.info(
        "定时生成简报触发，主题：%s，关键词：%s",
        ",".join(topics),
        ",".join(keywords or [])
    )  # 输出定时执行参数
    try:
        run_all_tasks_immediately(topics=topics, keywords=keywords or [])  # 同步执行完整流水线
    except Exception as exc:
        logger.error("定时生成简报失败: %s", exc, exc_info=True)
    finally:
        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
            data = json.loads(row.value) if row and row.value else {}
            if data.get("enabled"):
                _start_schedule_timer(
                    data.get("time", time_text),
                    _normalize_topics(data.get("topics")),
                    _normalize_keywords(data.get("keywords"))
                )  # 如果仍然启用，则继续安排下一次运行
        finally:
            db.close()


def _start_schedule_timer(time_text: str, topics: list[str], keywords: list[str] | None = None) -> None:  # 启动定时器
    global _schedule_timer
    _cancel_schedule_timer()  # 启动前先取消旧任务
    delay = _seconds_until_run(time_text)
    with _schedule_lock:
        _schedule_timer = threading.Timer(delay, _run_scheduled_brief, args=(topics, time_text, keywords or []))
        _schedule_timer.daemon = True
        _schedule_timer.start()
    logger.info(
        "已开始定时生成简报，时间：%s，主题：%s，关键词：%s",
        time_text,
        ",".join(topics),
        ",".join(keywords or [])
    )  # 输出当前定时配置


def restore_schedule_timer() -> None:  # 后端启动时恢复定时生成配置
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
        data = json.loads(row.value) if row and row.value else {}
        topics = _normalize_topics(data.get("topics"))
        keywords = _normalize_keywords(data.get("keywords"))
        if data.get("enabled") and topics:
            _start_schedule_timer(data.get("time", "07:00"), topics, keywords)  # 根据数据库配置恢复定时器
    except Exception as exc:
        logger.error("恢复定时生成配置失败: %s", exc, exc_info=True)
    finally:
        db.close()


def _submit_task(task, background_tasks: BackgroundTasks, *args, **kwargs):  # 优先提交异步任务，失败时降级后台任务
    try:
        task.delay(*args, **kwargs)
        return "queued"
    except Exception as exc:
        logger.warning("Celery task submit failed, fallback to FastAPI background task: %s", exc)
        background_tasks.add_task(task, *args, **kwargs)
        return "background"


@router.post("/crawl")  # 触发爬虫任务
def trigger_crawl(background_tasks: BackgroundTasks):
    mode = _submit_task(crawl_all_sources, background_tasks, process_inline=True)  # 同步处理当天文章入库
    return ok({"submitted": True, "mode": mode}, "Crawl task triggered")


@router.post("/ai-process")  # 触发 AI 处理任务
def trigger_ai_process(background_tasks: BackgroundTasks):
    mode = _submit_task(ai_process_articles, background_tasks)
    return ok({"submitted": True, "mode": mode}, "AI process task triggered")


@router.post("/generate-brief")  # 一键生成简报接口
def trigger_generate_brief(payload: GenerateBriefRequest | None = None, db: Session = Depends(get_db)):
    selected_topics = _normalize_topics(payload.topics if payload else [])  # 规整前端主题
    selected_keywords = _normalize_keywords(payload.keywords if payload else [])  # 规整前端关键词
    if not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")  # 主题必选

    if payload:
        payload_dict = payload.model_dump()
        payload_dict["topics"] = selected_topics
        payload_dict["keywords"] = selected_keywords
        _upsert_setting(db, "last_generate_options", payload_dict)  # 保存最近一次生成选项
        db.commit()

    logger.info(
        "前端触发一键生成当日简报，开始同步执行完整流水线，主题：%s，关键词：%s",
        ",".join(selected_topics),
        ",".join(selected_keywords)
    )  # 输出本次生成参数
    result = run_all_tasks_immediately(topics=selected_topics, keywords=selected_keywords)  # 同步执行完整流水线
    logger.info("前端一键生成当日简报流程结束。")
    return ok({"completed": True, "result": result}, "Generate brief task completed")


@router.post("/schedule")  # 保存定时生成配置接口
def save_schedule(payload: ScheduleRequest, db: Session = Depends(get_db)):
    selected_topics = _normalize_topics(payload.topics)  # 规整主题
    selected_keywords = _normalize_keywords(payload.keywords)  # 规整关键词
    if payload.enabled and not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")  # 定时生成时主题必选

    try:
        _seconds_until_run(payload.time)  # 校验时间格式
    except Exception:
        raise HTTPException(status_code=400, detail="定时时间格式必须为 HH:mm")

    value = payload.model_dump()
    value["topics"] = selected_topics
    value["keywords"] = selected_keywords
    _upsert_setting(db, "schedule", value)  # 保存定时配置
    db.commit()

    if payload.enabled:
        _start_schedule_timer(payload.time, selected_topics, selected_keywords)  # 启动定时任务
        return ok(value, "schedule started")

    _cancel_schedule_timer()  # 关闭定时任务
    return ok(value, "schedule stopped")


@router.post("/run-all")  # 触发完整流水线接口
def trigger_run_all(background_tasks: BackgroundTasks):
    mode = _submit_task(run_all_tasks_immediately, background_tasks)
    return ok({"submitted": True, "mode": mode}, "Full pipeline task triggered immediately")
