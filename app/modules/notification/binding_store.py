from app.database import SessionLocal
from app.modules.common.settings_store import load_json_setting


def load_binding_settings() -> dict:
    """读取前端保存的发送绑定设置。"""

    db = SessionLocal()
    try:
        return load_json_setting(db, "bindings", default={}) or {}
    finally:
        db.close()


def channel_options(channel_data: dict | None) -> dict:
    """补齐单个发送通道的内容开关默认值。"""

    data = channel_data or {}
    return {
        "include_brief": bool(data.get("include_brief", True)),
        "include_weather": bool(data.get("include_weather", False)),
        "include_typhoon": bool(data.get("include_typhoon", False)),
    }


def should_fetch_weather(bindings: dict | None) -> bool:
    """判断当前是否需要额外查询天气数据。

    技术原理：
    1. 只有当邮箱或飞书任一通道勾选天气/台风时才查询天气。
    2. 这样可以避免无意义的外部天气 API 调用。
    """

    bindings = bindings or {}
    for channel_name in ("email", "feishu"):
        options = channel_options(bindings.get(channel_name))
        if options["include_weather"] or options["include_typhoon"]:
            return True
    return False
