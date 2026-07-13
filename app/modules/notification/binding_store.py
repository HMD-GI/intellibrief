from app.database import SessionLocal
from app.modules.common.settings_store import load_json_setting


def load_binding_settings(user_key: str | None = None) -> dict:
    """读取前端保存的发送设置。

    技术说明：
    1. 发送设置属于结构化 JSON 配置，统一存入数据库中的 settings 表。
    2. 通过 user_key 参与实际存储键生成，实现不同用户之间的发送设置隔离。
    3. 当 user_key 为空时，回退到默认用户空间，保证兼容旧数据。
    """

    db = SessionLocal()
    try:
        return load_json_setting(db, "bindings", default={}, user_key=user_key) or {}
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

    技术说明：
    1. 只有邮箱或飞书任一通道勾选天气或台风时，才查询天气接口。
    2. 这样可以减少无意义的第三方天气 API 请求。
    """

    bindings = bindings or {}
    for channel_name in ("email", "feishu"):
        options = channel_options(bindings.get(channel_name))
        if options["include_weather"] or options["include_typhoon"]:
            return True
    return False
