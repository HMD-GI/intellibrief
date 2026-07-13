import json
from copy import deepcopy

from app.models.setting import AppSetting


SCOPED_SETTING_KEYS = {
    "bindings",
    "weather_preferences",
    "last_generate_options",
    "send_schedule_email",
    "send_schedule_feishu",
}


def normalize_user_key(user_key: str | None) -> str:
    """规整用户标识，用于设置隔离。"""

    value = (user_key or "").strip()
    return value or "default"


def build_setting_storage_key(key: str, user_key: str | None = None) -> str:
    """根据设置键和用户标识生成实际存储键。"""

    if key in SCOPED_SETTING_KEYS:
        return f"{key}::user::{normalize_user_key(user_key)}"
    return key


def load_json_setting(db, key: str, default=None, user_key: str | None = None):
    """读取 JSON 设置。

    技术原理：
    1. 所有结构化设置统一走同一个读入口，避免每个功能模块重复写 JSON 解析逻辑。
    2. 通过 default 的深拷贝，避免调用方拿到共享可变对象后互相污染。
    """

    storage_key = build_setting_storage_key(key, user_key)
    row = db.query(AppSetting).filter(AppSetting.key == storage_key).first()
    if not row or not row.value:
        return deepcopy(default)
    try:
        return json.loads(row.value)
    except Exception:
        return deepcopy(default)


def save_json_setting(db, key: str, value, user_key: str | None = None) -> None:
    """保存 JSON 设置。"""

    payload = json.dumps(value, ensure_ascii=False)
    storage_key = build_setting_storage_key(key, user_key)
    row = db.query(AppSetting).filter(AppSetting.key == storage_key).first()
    if row is None:
        row = AppSetting(key=storage_key, value=payload)
        db.add(row)
    else:
        row.value = payload
