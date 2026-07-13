import json
import logging
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.response import ok
from app.database import SessionLocal, get_db
from app.models.setting import AppSetting
from app.modules.common.settings_store import load_json_setting, normalize_user_key, save_json_setting
from scheduler.tasks import (
    ai_process_articles,
    crawl_all_sources,
    run_all_tasks_immediately,
    send_existing_briefs_now,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

# 使用进程内定时器承接“定时生成”功能。
# 原理是把配置存进数据库，再由当前进程恢复并触发；这部分仍是全局任务配置，不做用户隔离。
_schedule_timer: threading.Timer | None = None
_schedule_lock = threading.Lock()
_send_schedule_timers: dict[str, threading.Timer] = {}
_send_schedule_lock = threading.Lock()


class GenerateBriefRequest(BaseModel):
    """一键生成请求体。"""

    topics: list[str] = []
    keywords: list[str] = []
    topic_keywords: dict[str, list[str]] = {}
    send_email: bool = False
    send_feishu: bool = False


class ScheduleRequest(BaseModel):
    """定时生成请求体。"""

    time: str
    topics: list[str] = []
    keywords: list[str] = []
    topic_keywords: dict[str, list[str]] = {}
    enabled: bool = True


class SendNowRequest(BaseModel):
    """立即发送请求体。"""

    channel: str


class SendScheduleRequest(BaseModel):
    channel: str
    time: str
    enabled: bool = True


def _request_user_key(request: Request) -> str:
    """从请求头读取当前用户标识。

    技术说明：
    1. 当前项目还没有完整的鉴权体系，因此使用 X-User-Key 作为最小可行隔离键。
    2. 前端会把当前用户标识持久化到浏览器并附加到每次请求头中。
    """

    return normalize_user_key(request.headers.get("X-User-Key"))


def _normalize_topics(topics: list[str] | None) -> list[str]:
    """规整主题列表。"""

    return [topic.strip() for topic in (topics or []) if topic and topic.strip()]


def _normalize_keywords(keywords: list[str] | None) -> list[str]:
    """规整关键词列表。"""

    return [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]


def _normalize_topic_keywords(
    topic_keywords: dict[str, list[str]] | None,
    topics: list[str] | None = None,
) -> dict[str, list[str]]:
    """规整按主题拆分的关键词映射。"""

    allowed_topics = set(_normalize_topics(topics))
    normalized: dict[str, list[str]] = {}
    for topic, keywords in (topic_keywords or {}).items():
        clean_topic = (topic or "").strip()
        if not clean_topic:
            continue
        if allowed_topics and clean_topic not in allowed_topics:
            continue
        clean_keywords = _normalize_keywords(keywords)
        if clean_keywords:
            normalized[clean_topic] = clean_keywords
    return normalized


def _upsert_setting(db: Session, key: str, value_dict: dict) -> None:
    """保存全局设置。

    技术说明：
    1. schedule 仍然是全局配置，因为它由单个后端进程恢复和触发。
    2. 只有 bindings、weather_preferences、last_generate_options 这类用户界面配置才做用户隔离。
    """

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = json.dumps(value_dict, ensure_ascii=False)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _seconds_until_run(time_text: str) -> float:
    """计算距离下一次运行的秒数。"""

    hour, minute = [int(part) for part in time_text.split(":", 1)]
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return max(1.0, (next_run - now).total_seconds())


def _time_to_minutes(time_text: str) -> int:
    """Convert HH:mm to minutes in day."""

    hour, minute = [int(part) for part in time_text.split(":", 1)]
    return hour * 60 + minute


def _send_schedule_key(channel: str) -> str:
    """Build scoped setting key for send schedule."""

    return f"send_schedule_{channel}"


def _send_timer_key(channel: str, user_key: str) -> str:
    """Build in-process timer key."""

    return f"{channel}::{normalize_user_key(user_key)}"


def _cancel_schedule_timer() -> None:
    """取消当前定时器。"""

    global _schedule_timer
    with _schedule_lock:
        if _schedule_timer:
            _schedule_timer.cancel()
            _schedule_timer = None


def _cancel_send_schedule_timer(channel: str, user_key: str) -> None:
    """Cancel one send timer."""

    timer_key = _send_timer_key(channel, user_key)
    with _send_schedule_lock:
        timer = _send_schedule_timers.pop(timer_key, None)
        if timer:
            timer.cancel()


def _validate_send_schedule(db: Session, send_time: str) -> None:
    """Ensure send schedule is not earlier than generate schedule and generate is enabled."""

    generate_schedule = load_json_setting(db, "schedule", default={}) or {}
    if not generate_schedule.get("enabled"):
        raise HTTPException(status_code=400, detail="请先开启定时生成简报，再设置定时发送。")
    generate_time = generate_schedule.get("time") or "07:00"
    if _time_to_minutes(generate_time) > _time_to_minutes(send_time):
        raise HTTPException(status_code=400, detail="定时发送时间不能早于定时生成简报时间。")


def _run_scheduled_send(channel: str, user_key: str, time_text: str) -> None:
    """Run scheduled send and re-arm timer if still enabled."""

    logger.info("定时发送触发，通道：%s，用户：%s", channel, user_key)
    try:
        send_existing_briefs_now(channel=channel, user_key=user_key)
    except Exception as exc:
        logger.error("定时发送失败：channel=%s user=%s error=%s", channel, user_key, exc, exc_info=True)
    finally:
        db = SessionLocal()
        try:
            data = load_json_setting(db, _send_schedule_key(channel), default={}, user_key=user_key) or {}
            if data.get("enabled"):
                _start_send_schedule_timer(channel, user_key, data.get("time", time_text))
        finally:
            db.close()


def _start_send_schedule_timer(channel: str, user_key: str, time_text: str) -> None:
    """Start one send timer."""

    _cancel_send_schedule_timer(channel, user_key)
    delay = _seconds_until_run(time_text)
    timer_key = _send_timer_key(channel, user_key)
    with _send_schedule_lock:
        timer = threading.Timer(delay, _run_scheduled_send, args=(channel, normalize_user_key(user_key), time_text))
        timer.daemon = True
        timer.start()
        _send_schedule_timers[timer_key] = timer
    logger.info("已开启定时发送，通道：%s，用户：%s，时间：%s", channel, user_key, time_text)


def _run_scheduled_brief(
    topics: list[str],
    time_text: str,
    keywords: list[str] | None = None,
    topic_keywords: dict[str, list[str]] | None = None,
) -> None:
    """定时触发完整流水线。"""

    logger.info(
        "定时生成简报触发，主题：%s，关键词：%s",
        ",".join(topics),
        json.dumps(topic_keywords or keywords or [], ensure_ascii=False),
    )
    try:
        run_all_tasks_immediately(
            topics=topics,
            keywords=keywords or [],
            topic_keywords=topic_keywords or {},
        )
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
                    _normalize_keywords(data.get("keywords")),
                    _normalize_topic_keywords(data.get("topic_keywords"), data.get("topics")),
                )
        finally:
            db.close()


def _start_schedule_timer(
    time_text: str,
    topics: list[str],
    keywords: list[str] | None = None,
    topic_keywords: dict[str, list[str]] | None = None,
) -> None:
    """启动定时器。"""

    global _schedule_timer
    _cancel_schedule_timer()
    delay = _seconds_until_run(time_text)
    with _schedule_lock:
        _schedule_timer = threading.Timer(
            delay,
            _run_scheduled_brief,
            args=(topics, time_text, keywords or [], topic_keywords or {}),
        )
        _schedule_timer.daemon = True
        _schedule_timer.start()
    logger.info(
        "已开始定时生成简报，时间：%s，主题：%s，关键词：%s",
        time_text,
        ",".join(topics),
        json.dumps(topic_keywords or keywords or [], ensure_ascii=False),
    )


def restore_schedule_timer() -> None:
    """后端启动时恢复定时生成配置。"""

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "schedule").first()
        data = json.loads(row.value) if row and row.value else {}
        topics = _normalize_topics(data.get("topics"))
        keywords = _normalize_keywords(data.get("keywords"))
        topic_keywords = _normalize_topic_keywords(data.get("topic_keywords"), topics)
        if data.get("enabled") and topics:
            _start_schedule_timer(data.get("time", "07:00"), topics, keywords, topic_keywords)
    except Exception as exc:
        logger.error("恢复定时生成配置失败: %s", exc, exc_info=True)
    finally:
        db.close()


def restore_send_schedule_timers() -> None:
    """Restore all user-scoped send schedules on startup."""

    db = SessionLocal()
    try:
        rows = db.query(AppSetting).filter(
            (AppSetting.key.like("send_schedule_email::user::%"))
            | (AppSetting.key.like("send_schedule_feishu::user::%"))
        ).all()
        for row in rows:
            try:
                data = json.loads(row.value) if row.value else {}
            except Exception:
                continue
            if not data.get("enabled"):
                continue
            channel = "email" if row.key.startswith("send_schedule_email::user::") else "feishu"
            user_key = row.key.split("::user::", 1)[-1]
            try:
                _validate_send_schedule(db, data.get("time", "07:30"))
            except HTTPException as exc:
                logger.warning("Skip restoring send schedule for user=%s channel=%s: %s", user_key, channel, exc.detail)
                continue
            _start_send_schedule_timer(channel, user_key, data.get("time", "07:30"))
    finally:
        db.close()


def _list_enabled_send_schedule_times(db: Session) -> list[tuple[str, str]]:
    """Collect enabled send schedules across users."""

    rows = db.query(AppSetting).filter(
        (AppSetting.key.like("send_schedule_email::user::%"))
        | (AppSetting.key.like("send_schedule_feishu::user::%"))
    ).all()
    items: list[tuple[str, str]] = []
    for row in rows:
        try:
            data = json.loads(row.value) if row.value else {}
        except Exception:
            continue
        if not data.get("enabled"):
            continue
        channel = "email" if row.key.startswith("send_schedule_email::user::") else "feishu"
        items.append((channel, data.get("time", "07:30")))
    return items


def _submit_task(task, background_tasks: BackgroundTasks, *args, **kwargs):
    """优先提交 Celery 任务，失败时回退到 FastAPI 后台任务。"""

    try:
        task.delay(*args, **kwargs)
        return "queued"
    except Exception as exc:
        logger.warning("Celery task submit failed, fallback to FastAPI background task: %s", exc)
        background_tasks.add_task(task, *args, **kwargs)
        return "background"


@router.post("/crawl")
def trigger_crawl(background_tasks: BackgroundTasks):
    """触发爬虫任务。"""

    mode = _submit_task(crawl_all_sources, background_tasks, process_inline=True)
    return ok({"submitted": True, "mode": mode}, "Crawl task triggered")


@router.post("/ai-process")
def trigger_ai_process(background_tasks: BackgroundTasks):
    """触发 AI 处理任务。"""

    mode = _submit_task(ai_process_articles, background_tasks)
    return ok({"submitted": True, "mode": mode}, "AI process task triggered")


@router.post("/generate-brief")
def trigger_generate_brief(
    request: Request,
    payload: GenerateBriefRequest | None = None,
    db: Session = Depends(get_db),
):
    """一键生成当天简报。"""

    user_key = _request_user_key(request)
    selected_topics = _normalize_topics(payload.topics if payload else [])
    selected_keywords = _normalize_keywords(payload.keywords if payload else [])
    selected_topic_keywords = _normalize_topic_keywords(payload.topic_keywords if payload else {}, selected_topics)
    if not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")

    if payload:
        payload_dict = payload.model_dump()
        payload_dict["topics"] = selected_topics
        payload_dict["keywords"] = selected_keywords
        payload_dict["topic_keywords"] = selected_topic_keywords
        save_json_setting(db, "last_generate_options", payload_dict, user_key=user_key)
        db.commit()

    logger.info(
        "前端触发一键生成当日简报，开始同步执行完整流水线，用户：%s，主题：%s，关键词：%s",
        user_key,
        ",".join(selected_topics),
        json.dumps(selected_topic_keywords, ensure_ascii=False) if selected_topic_keywords else ",".join(selected_keywords),
    )
    result = run_all_tasks_immediately(
        topics=selected_topics,
        keywords=selected_keywords,
        topic_keywords=selected_topic_keywords,
        user_key=user_key,
    )
    logger.info("前端一键生成当日简报流程结束。")
    return ok({"completed": True, "result": result}, "Generate brief task completed")


@router.post("/schedule")
def save_schedule(payload: ScheduleRequest, db: Session = Depends(get_db)):
    """保存定时生成配置。"""

    selected_topics = _normalize_topics(payload.topics)
    selected_keywords = _normalize_keywords(payload.keywords)
    selected_topic_keywords = _normalize_topic_keywords(payload.topic_keywords, selected_topics)
    if payload.enabled and not selected_topics:
        raise HTTPException(status_code=400, detail="请至少选择一个主题")
    try:
        _seconds_until_run(payload.time)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="定时时间格式必须为 HH:mm") from exc

    enabled_send_schedules = _list_enabled_send_schedule_times(db)
    if not payload.enabled and enabled_send_schedules:
        raise HTTPException(status_code=400, detail="已有定时发送任务开启，请先关闭定时发送，再关闭定时生成简报。")
    for channel_name, send_time in enabled_send_schedules:
        if payload.enabled and _time_to_minutes(payload.time) > _time_to_minutes(send_time):
            raise HTTPException(
                status_code=400,
                detail=f"定时生成简报时间不能晚于已开启的定时发送{channel_name}时间（{send_time}）。",
            )

    value = payload.model_dump()
    value["topics"] = selected_topics
    value["keywords"] = selected_keywords
    value["topic_keywords"] = selected_topic_keywords
    _upsert_setting(db, "schedule", value)
    db.commit()

    if payload.enabled:
        _start_schedule_timer(payload.time, selected_topics, selected_keywords, selected_topic_keywords)
        return ok(value, "schedule started")

    _cancel_schedule_timer()
    return ok(value, "schedule stopped")


@router.post("/send-schedule")
def save_send_schedule(request: Request, payload: SendScheduleRequest, db: Session = Depends(get_db)):
    """保存定时发送配置。"""

    channel = (payload.channel or "").strip().lower()
    if channel not in {"email", "feishu"}:
        raise HTTPException(status_code=400, detail="channel 只支持 email 或 feishu")
    try:
        _seconds_until_run(payload.time)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="定时发送时间格式必须为 HH:mm") from exc

    user_key = _request_user_key(request)
    value = {"channel": channel, "time": payload.time, "enabled": bool(payload.enabled)}
    if payload.enabled:
        _validate_send_schedule(db, payload.time)
        _start_send_schedule_timer(channel, user_key, payload.time)
    else:
        _cancel_send_schedule_timer(channel, user_key)

    save_json_setting(db, _send_schedule_key(channel), value, user_key=user_key)
    db.commit()
    return ok(value, "send schedule started" if payload.enabled else "send schedule stopped")


@router.post("/run-all")
def trigger_run_all(background_tasks: BackgroundTasks):
    """触发完整流水线。"""

    mode = _submit_task(run_all_tasks_immediately, background_tasks)
    return ok({"submitted": True, "mode": mode}, "Full pipeline task triggered immediately")


@router.post("/send-now")
def trigger_send_now(request: Request, payload: SendNowRequest):
    """按当前发送设置立即补发当天简报。"""

    channel = (payload.channel or "").strip().lower()
    if channel not in {"email", "feishu"}:
        raise HTTPException(status_code=400, detail="channel 只支持 email 或 feishu")
    user_key = _request_user_key(request)
    result = send_existing_briefs_now(channel=channel, user_key=user_key)
    return ok(result, result.get("message", "send completed"))
