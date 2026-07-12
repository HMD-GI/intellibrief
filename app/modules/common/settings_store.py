import json
from copy import deepcopy

from app.models.setting import AppSetting


def load_json_setting(db, key: str, default=None):
    """读取 JSON 设置。

    技术原理：
    1. 所有结构化设置统一走同一个读入口，避免每个功能模块重复写 JSON 解析逻辑。
    2. 通过 default 的深拷贝，避免调用方拿到共享可变对象后互相污染。
    """

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row or not row.value:
        return deepcopy(default)
    try:
        return json.loads(row.value)
    except Exception:
        return deepcopy(default)


def save_json_setting(db, key: str, value) -> None:
    """保存 JSON 设置。"""

    payload = json.dumps(value, ensure_ascii=False)
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        row = AppSetting(key=key, value=payload)
        db.add(row)
    else:
        row.value = payload

