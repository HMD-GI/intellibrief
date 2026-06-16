import logging  # 导入日志模块
import threading  # 导入线程模块，用于本进程定时生成
from datetime import datetime, timedelta  # 导入时间计算工具
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException  # 导入 APIRouter 等组件
from pydantic import BaseModel  # 导入请求体模型
from sqlalchemy.orm import Session  # 导入数据库会话类型
import json  # 导入 JSON
from app.api.response import ok  # 导入统一响应函数
from app.database import get_db, SessionLocal  # 导入数据库依赖
from app.models.setting import AppSetting  # 导入设置模型
from scheduler.tasks import crawl_all_sources, ai_process_articles, generate_and_push_brief, run_all_tasks_immediately  # 导入 Celery 任务函数

router = APIRouter(prefix="/tasks", tags=["tasks"])  # 创建任务管理路由实例，前缀 /tasks
logger = logging.getLogger(__name__)  # 初始化日志记录器
_schedule_timer: threading.Timer | None = None  # 保存当前定时器实例，便于取消定时任务
_schedule_lock = threading.Lock()  # 保护定时器状态，避免并发点击造成重复定时


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

def _normalize_topics(topics: list[str] | None) -> list[str]:  # 规范化主题列表
    return [topic.strip() for topic in (topics or []) if topic and topic.strip()]  # 去掉空值和首尾空白

def _upsert_setting(db: Session, key: str, value_dict: dict) -> None:  # 保存通用设置
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = json.dumps(value_dict, ensure_ascii=False)
    if not row:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value

def _seconds_until_run(time_text: str) -> float:  # 计算距离下一次定时时间的秒数
    hour, minute = [int(part) for part in time_text.split(":", 1)]
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return max(1.0, (next_run - now).total_seconds())

def _cancel_schedule_timer() -> None:  # 取消当前定时任务
    global _schedule_timer
    with _schedule_lock:
        if _schedule_timer:
            _schedule_timer.cancel()
            _schedule_timer = None

def _run_scheduled_brief(topics: list[str], time_text: str) -> None:  # 定时器触发后的执行函数
    logger.info(f"定时生成简报触发，主题：{', '.join(topics)}")  # 记录定时触发日志
    try:
        run_all_tasks_immediately(topics=topics)  # 同步执行完整流水线，终端显示全流程日志
    except Exception as exc:
        logger.error("定时生成简报失败: %s", exc, exc_info=True)
    finally:
        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
            data = json.loads(row.value) if row and row.value else {}
            if data.get("enabled"):
                _start_schedule_timer(data.get("time", time_text), _normalize_topics(data.get("topics")))  # 若仍启用则安排下一次
        finally:
            db.close()

def _start_schedule_timer(time_text: str, topics: list[str]) -> None:  # 启动定时生成
    global _schedule_timer
    _cancel_schedule_timer()  # 启动前先取消旧定时器
    delay = _seconds_until_run(time_text)
    with _schedule_lock:
        _schedule_timer = threading.Timer(delay, _run_scheduled_brief, args=(topics, time_text))
        _schedule_timer.daemon = True
        _schedule_timer.start()
    logger.info(f"已开始定时生成简报，时间：{time_text}，主题：{', '.join(topics)}")

def restore_schedule_timer() -> None:  # 应用启动时恢复已启用的定时生成
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
        data = json.loads(row.value) if row and row.value else {}
        topics = _normalize_topics(data.get("topics"))
        if data.get("enabled") and topics:
            _start_schedule_timer(data.get("time", "07:00"), topics)  # 根据数据库配置恢复定时器
    except Exception as exc:
        logger.error("恢复定时生成配置失败: %s", exc, exc_info=True)
    finally:
        db.close()

@router.post("/crawl")  # 注册触发全量爬虫的 POST 路由
def trigger_crawl(background_tasks: BackgroundTasks):  # 处理函数
    mode = _submit_task(crawl_all_sources, background_tasks, process_inline=True)  # 抓取详情页日期为当天的全部文章并同步入库
    return ok({"submitted": True, "mode": mode}, "Crawl task triggered")  # 返回触发成功消息

@router.post("/ai-process")  # 注册触发 AI 处理流程的 POST 路由
def trigger_ai_process(background_tasks: BackgroundTasks):  # 处理函数
    mode = _submit_task(ai_process_articles, background_tasks)  # 异步调用 AI 处理任务
    return ok({"submitted": True, "mode": mode}, "AI process task triggered")  # 返回触发成功消息

@router.post("/generate-brief")  # 注册触发生成简报的 POST 路由
def trigger_generate_brief(payload: GenerateBriefRequest | None = None, db: Session = Depends(get_db)):  # 处理函数
    selected_topics = _normalize_topics(payload.topics if payload else [])  # 获取前端选择主题
    if not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")  # 主题必选，前端未选时直接提示
    if payload:
        payload_dict = payload.model_dump()
        payload_dict["topics"] = selected_topics
        _upsert_setting(db, "last_generate_options", payload_dict)  # 保存最近一次生成选项，不修改数据源主题
        db.commit()
    logger.info("前端触发一键生成当日简报，开始同步执行完整流水线...")  # 记录前端触发日志，便于终端查看全流程
    result = run_all_tasks_immediately(topics=selected_topics)  # 同步执行完整流水线，等待爬取、AI 处理、简报生成全部完成
    logger.info("前端一键生成当日简报流程结束。")  # 记录流程结束日志
    return ok({"completed": True, "result": result}, "Generate brief task completed")  # 返回生成完成消息


@router.post("/schedule")  # 注册保存定时生成配置接口
def save_schedule(payload: ScheduleRequest, db: Session = Depends(get_db)):
    selected_topics = _normalize_topics(payload.topics)  # 获取定时生成主题
    if payload.enabled and not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")  # 开始定时前必须选择主题
    try:
        _seconds_until_run(payload.time)  # 校验时间格式是否合法
    except Exception:
        raise HTTPException(status_code=400, detail="定时时间格式必须为 HH:mm")
    value = payload.model_dump()
    value["topics"] = selected_topics
    _upsert_setting(db, "schedule", value)  # 保存定时配置
    db.commit()
    if payload.enabled:
        _start_schedule_timer(payload.time, selected_topics)  # 启动定时生成
        return ok(value, "schedule started")
    _cancel_schedule_timer()  # 关闭定时生成
    return ok(value, "schedule stopped")

@router.post("/run-all")  # 注册触发完整流水线的 POST 路由
def trigger_run_all(background_tasks: BackgroundTasks):  # 处理函数
    """
    一键触发完整的流水线（测试用）：爬取 -> AI分析 -> 生成简报
    """
    mode = _submit_task(run_all_tasks_immediately, background_tasks)  # 异步调用全流程任务
    return ok({"submitted": True, "mode": mode}, "Full pipeline task triggered immediately")  # 返回触发成功消息
