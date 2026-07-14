import json
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.response import ok
from app.database import SessionLocal, get_db
from app.models.setting import AppSetting
from app.modules.common.settings_store import load_json_setting, normalize_user_key, save_json_setting
from app.modules.scheduler import runtime_scheduler
from scheduler.tasks import (
    ai_process_articles,
    crawl_all_sources,
    run_all_tasks_immediately,
    send_existing_briefs_now,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

GENERATE_SCHEDULE_KEY = "schedule"
SEND_CHANNELS = {"email", "feishu"}
BRIEF_DATE_SCOPES = ("today", "yesterday")
GENERATE_JOB_PREFIX = "generate::"
SEND_JOB_PREFIX = "send::"


class GenerateBriefRequest(BaseModel):
    """一键生成简报请求体。"""

    topics: list[str] = []
    keywords: list[str] = []
    topic_keywords: dict[str, list[str]] = {}
    send_email: bool = False
    send_feishu: bool = False


class ScheduleItemRequest(BaseModel):
    """单个定时生成项。

    技术说明：
    1. 一个定时生成配置拆成多条 item，每条 item 对应一天中的一个时间点。
    2. 每条 item 都可以独立保存主题和关键词快照，满足“多个时间段生成不同主题简报”。
    """

    id: str | None = None
    time: str
    topics: list[str] = []
    keywords: list[str] = []
    topic_keywords: dict[str, list[str]] = {}
    enabled: bool = True


class ScheduleRequest(BaseModel):
    """定时生成请求体。

    兼容说明：
    1. 新版本优先使用 items 数组。
    2. 保留旧版 time/topics/keywords/topic_keywords 字段，便于兼容历史前端调用。
    """

    enabled: bool = True
    items: list[ScheduleItemRequest] = []
    time: str | None = None
    topics: list[str] = []
    keywords: list[str] = []
    topic_keywords: dict[str, list[str]] = {}


class SendNowRequest(BaseModel):
    """立即发送请求体。"""

    channel: str
    brief_date_scopes: list[str] = []


class SendScheduleRequest(BaseModel):
    """定时发送请求体。"""

    channel: str
    time: str
    enabled: bool = True
    brief_date_scopes: list[str] = []


def _request_user_key(request: Request) -> str:
    """从请求头读取当前用户标识。"""

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


def _normalize_brief_date_scopes(scopes: list[str] | None) -> list[str]:
    """规整简报日期范围。

    技术说明：
    1. 这里只接受 today / yesterday 两种相对日期。
    2. 定时发送属于周期规则，使用相对日期比保存绝对日期更合理。
    """

    normalized: list[str] = []
    for scope in scopes or []:
        clean_scope = (scope or "").strip().lower()
        if clean_scope in BRIEF_DATE_SCOPES and clean_scope not in normalized:
            normalized.append(clean_scope)
    return normalized or ["today"]


def _resolve_target_brief_dates(scopes: list[str] | None) -> list[date]:
    """将 today / yesterday 规则解析成真实日期。"""

    today_value = date.today()
    target_dates: list[date] = []
    for scope in _normalize_brief_date_scopes(scopes):
        if scope == "today":
            target_dates.append(today_value)
        elif scope == "yesterday":
            target_dates.append(today_value - timedelta(days=1))
    return target_dates


def _upsert_setting(db: Session, key: str, value_dict: dict) -> None:
    """保存全局设置。"""

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = json.dumps(value_dict, ensure_ascii=False)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _validate_time_text(time_text: str) -> None:
    """校验 HH:mm 时间格式。"""

    try:
        hour, minute = [int(part) for part in time_text.split(":", 1)]
    except Exception as exc:
        raise HTTPException(status_code=400, detail="时间格式必须为 HH:mm") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=400, detail="时间格式必须为 HH:mm")


def _time_to_minutes(time_text: str) -> int:
    """将 HH:mm 转换成一天中的分钟数。"""

    _validate_time_text(time_text)
    hour, minute = [int(part) for part in time_text.split(":", 1)]
    return hour * 60 + minute


def _send_schedule_key(channel: str) -> str:
    """构造发送定时配置键。"""

    return f"send_schedule_{channel}"


def _generate_job_id(schedule_id: str) -> str:
    """构造定时生成 Job ID。"""

    return f"{GENERATE_JOB_PREFIX}{schedule_id}"


def _send_job_id(channel: str, user_key: str) -> str:
    """构造定时发送 Job ID。"""

    return f"{SEND_JOB_PREFIX}{channel}::{normalize_user_key(user_key)}"


def _normalize_schedule_item_payload(item: dict[str, Any] | ScheduleItemRequest) -> dict[str, Any]:
    """规整单个定时生成项。"""

    raw_item = item.model_dump() if isinstance(item, ScheduleItemRequest) else dict(item or {})
    item_id = (raw_item.get("id") or "").strip() or f"schedule_{uuid.uuid4().hex[:12]}"
    time_text = (raw_item.get("time") or "").strip()
    _validate_time_text(time_text)
    topics = _normalize_topics(raw_item.get("topics"))
    keywords = _normalize_keywords(raw_item.get("keywords"))
    topic_keywords = _normalize_topic_keywords(raw_item.get("topic_keywords"), topics)
    return {
        "id": item_id,
        "time": time_text,
        "topics": topics,
        "keywords": keywords,
        "topic_keywords": topic_keywords,
        "enabled": bool(raw_item.get("enabled", True)),
    }


def _normalize_schedule_payload(payload: ScheduleRequest | dict[str, Any] | None) -> dict[str, Any]:
    """将新旧两种定时生成配置统一规整成 items 数组结构。"""

    raw_payload = payload.model_dump() if isinstance(payload, ScheduleRequest) else dict(payload or {})
    normalized_items: list[dict[str, Any]] = []

    if raw_payload.get("items"):
        for item in raw_payload.get("items") or []:
            normalized_items.append(_normalize_schedule_item_payload(item))
    elif raw_payload.get("time"):
        normalized_items.append(
            _normalize_schedule_item_payload(
                {
                    "id": raw_payload.get("id"),
                    "time": raw_payload.get("time"),
                    "topics": raw_payload.get("topics") or [],
                    "keywords": raw_payload.get("keywords") or [],
                    "topic_keywords": raw_payload.get("topic_keywords") or {},
                    "enabled": raw_payload.get("enabled", True),
                }
            )
        )

    return {
        "enabled": bool(raw_payload.get("enabled", True)),
        "items": normalized_items,
    }


def _load_schedule_value(db: Session) -> dict[str, Any]:
    """读取并规整定时生成配置。"""

    data = load_json_setting(db, GENERATE_SCHEDULE_KEY, default={}) or {}
    return _normalize_schedule_payload(data)


def _enabled_generate_items(schedule_value: dict[str, Any]) -> list[dict[str, Any]]:
    """提取已启用的定时生成项。"""

    if not schedule_value.get("enabled"):
        return []
    return [item for item in schedule_value.get("items") or [] if item.get("enabled") and item.get("topics")]


def _list_enabled_send_schedules(db: Session) -> list[dict[str, Any]]:
    """收集所有用户已启用的定时发送配置。"""

    rows = db.query(AppSetting).filter(
        (AppSetting.key.like("send_schedule_email::user::%"))
        | (AppSetting.key.like("send_schedule_feishu::user::%"))
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row.value) if row.value else {}
        except Exception:
            continue
        if not data.get("enabled"):
            continue
        channel = "email" if row.key.startswith("send_schedule_email::user::") else "feishu"
        items.append(
            {
                "channel": channel,
                "user_key": row.key.split("::user::", 1)[-1],
                "time": data.get("time", "07:30"),
                "brief_date_scopes": _normalize_brief_date_scopes(data.get("brief_date_scopes")),
            }
        )
    return items


def _validate_send_schedule(_db: Session, send_time: str, _brief_date_scopes: list[str] | None) -> None:
    """校验定时发送配置。

    当前规则：
    1. 仅校验时间格式是否合法。
    2. 不再要求“定时生成时间必须早于定时发送时间”。
    3. 发送与生成解耦，允许用户按自己的流程安排两类任务。
    """

    _validate_time_text(send_time)


def _validate_schedule_against_send_schedules(_db: Session, schedule_value: dict[str, Any]) -> None:
    """校验定时生成配置。

    当前规则：
    1. 仅保证定时项自身结构合法。
    2. 不再检查其与飞书、邮箱定时发送之间的先后关系。
    """

    for item in schedule_value.get("items") or []:
        _validate_time_text(item.get("time", ""))


def _upsert_generate_schedule_jobs(schedule_value: dict[str, Any]) -> None:
    """将数据库中的定时生成配置同步到 APScheduler。"""

    runtime_scheduler.remove_jobs_by_prefix(GENERATE_JOB_PREFIX)
    for item in _enabled_generate_items(schedule_value):
        runtime_scheduler.upsert_daily_job(
            job_id=_generate_job_id(item["id"]),
            func=_run_scheduled_brief,
            time_text=item["time"],
            args=(item["id"],),
        )


def _sync_send_schedule_job(channel: str, user_key: str, value: dict[str, Any]) -> None:
    """将单个发送配置同步到 APScheduler。"""

    job_id = _send_job_id(channel, user_key)
    if not value.get("enabled"):
        runtime_scheduler.remove_job(job_id)
        return

    runtime_scheduler.upsert_daily_job(
        job_id=job_id,
        func=_run_scheduled_send,
        time_text=value["time"],
        args=(channel, normalize_user_key(user_key)),
    )


def _run_scheduled_send(channel: str, user_key: str) -> None:
    """APScheduler 触发定时发送。"""

    logger.info("定时发送触发，通道：%s，用户：%s", channel, user_key)
    db = SessionLocal()
    try:
        data = load_json_setting(db, _send_schedule_key(channel), default={}, user_key=user_key) or {}
        if not data.get("enabled"):
            return
        send_existing_briefs_now(
            channel=channel,
            user_key=user_key,
            brief_date_scopes=_normalize_brief_date_scopes(data.get("brief_date_scopes")),
        )
    except Exception as exc:
        logger.error("定时发送失败：channel=%s user=%s error=%s", channel, user_key, exc, exc_info=True)
    finally:
        db.close()


def _run_scheduled_brief(schedule_id: str) -> None:
    """APScheduler 触发定时生成。"""

    db = SessionLocal()
    try:
        schedule_value = _load_schedule_value(db)
        if not schedule_value.get("enabled"):
            return
        target_item = next(
            (
                item
                for item in schedule_value.get("items") or []
                if item.get("id") == schedule_id and item.get("enabled")
            ),
            None,
        )
        if not target_item:
            return

        logger.info(
            "定时生成简报触发，任务：%s，主题：%s，关键词：%s",
            schedule_id,
            ",".join(target_item.get("topics") or []),
            json.dumps(target_item.get("topic_keywords") or target_item.get("keywords") or [], ensure_ascii=False),
        )
        run_all_tasks_immediately(
            topics=target_item.get("topics") or [],
            keywords=target_item.get("keywords") or [],
            topic_keywords=target_item.get("topic_keywords") or {},
        )
    except Exception as exc:
        logger.error("定时生成简报失败：schedule_id=%s error=%s", schedule_id, exc, exc_info=True)
    finally:
        db.close()


def restore_schedule_timer() -> None:
    """应用启动时恢复定时生成任务。"""

    db = SessionLocal()
    try:
        schedule_value = _load_schedule_value(db)
        _upsert_generate_schedule_jobs(schedule_value)
    except Exception as exc:
        logger.error("恢复定时生成配置失败: %s", exc, exc_info=True)
    finally:
        db.close()


def restore_send_schedule_timers() -> None:
    """应用启动时恢复定时发送任务。"""

    runtime_scheduler.remove_jobs_by_prefix(SEND_JOB_PREFIX)
    db = SessionLocal()
    try:
        for item in _list_enabled_send_schedules(db):
            try:
                _validate_send_schedule(db, item["time"], item["brief_date_scopes"])
            except HTTPException as exc:
                logger.warning(
                    "跳过恢复定时发送，用户=%s 通道=%s 原因=%s",
                    item["user_key"],
                    item["channel"],
                    exc.detail,
                )
                continue
            _sync_send_schedule_job(
                channel=item["channel"],
                user_key=item["user_key"],
                value={
                    "time": item["time"],
                    "enabled": True,
                    "brief_date_scopes": item["brief_date_scopes"],
                },
            )
    finally:
        db.close()


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
    """一键生成当日简报。"""

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
    """保存多时间段定时生成配置。"""

    schedule_value = _normalize_schedule_payload(payload)
    enabled_items = _enabled_generate_items(schedule_value)
    if schedule_value.get("enabled") and not enabled_items:
        raise HTTPException(status_code=400, detail="请至少配置一个已启用的定时生成项")

    _validate_schedule_against_send_schedules(db, schedule_value)

    _upsert_setting(db, GENERATE_SCHEDULE_KEY, schedule_value)
    db.commit()
    _upsert_generate_schedule_jobs(schedule_value)

    return ok(
        schedule_value,
        "schedule started" if enabled_items else "schedule stopped",
    )


@router.post("/send-schedule")
def save_send_schedule(request: Request, payload: SendScheduleRequest, db: Session = Depends(get_db)):
    """保存定时发送配置。"""

    channel = (payload.channel or "").strip().lower()
    if channel not in SEND_CHANNELS:
        raise HTTPException(status_code=400, detail="channel 只支持 email 或 feishu")

    _validate_time_text(payload.time)
    user_key = _request_user_key(request)
    brief_date_scopes = _normalize_brief_date_scopes(payload.brief_date_scopes)
    value = {
        "channel": channel,
        "time": payload.time,
        "enabled": bool(payload.enabled),
        "brief_date_scopes": brief_date_scopes,
    }

    if payload.enabled:
        _validate_send_schedule(db, payload.time, brief_date_scopes)

    save_json_setting(db, _send_schedule_key(channel), value, user_key=user_key)
    db.commit()
    _sync_send_schedule_job(channel, user_key, value)

    return ok(value, "send schedule started" if payload.enabled else "send schedule stopped")


@router.post("/run-all")
def trigger_run_all(background_tasks: BackgroundTasks):
    """触发完整流水线。"""

    mode = _submit_task(run_all_tasks_immediately, background_tasks)
    return ok({"submitted": True, "mode": mode}, "Full pipeline task triggered immediately")


@router.post("/send-now")
def trigger_send_now(request: Request, payload: SendNowRequest, db: Session = Depends(get_db)):
    """按当前发送设置立即发送简报。"""

    channel = (payload.channel or "").strip().lower()
    if channel not in SEND_CHANNELS:
        raise HTTPException(status_code=400, detail="channel 只支持 email 或 feishu")

    user_key = _request_user_key(request)
    brief_date_scopes = _normalize_brief_date_scopes(payload.brief_date_scopes)

    # 如果前端没有显式传递范围，则回退到该渠道已保存的发送设置。
    if not payload.brief_date_scopes:
        saved_value = load_json_setting(db, _send_schedule_key(channel), default={}, user_key=user_key) or {}
        brief_date_scopes = _normalize_brief_date_scopes(saved_value.get("brief_date_scopes"))

    result = send_existing_briefs_now(
        channel=channel,
        user_key=user_key,
        brief_date_scopes=brief_date_scopes,
    )
    result["brief_date_scopes"] = brief_date_scopes
    result["target_dates"] = [item.isoformat() for item in _resolve_target_brief_dates(brief_date_scopes)]
    return ok(result, result.get("message", "send completed"))
