import json  # 导入 JSON
from fastapi import APIRouter, Depends, Request  # 导入 FastAPI 组件
from pydantic import BaseModel  # 导入 BaseModel
from sqlalchemy.orm import Session  # 导入 Session
from app.api.response import ok  # 导入统一响应函数
from app.database import get_db  # 导入数据库依赖
from app.models.setting import AppSetting  # 导入设置模型
from app.modules.common.settings_store import build_setting_storage_key, load_json_setting, normalize_user_key, save_json_setting  # 导入按用户隔离的设置存取


router = APIRouter(prefix="/settings", tags=["settings"])  # 创建设置路由


class SettingPayload(BaseModel):  # 定义设置请求体
    key: str  # 设置键
    value: dict  # 设置值


def _request_user_key(request: Request) -> str:
    """从请求头读取当前用户标识。"""

    return normalize_user_key(request.headers.get("X-User-Key"))


@router.get("/")  # 获取所有设置
def list_settings(request: Request, db: Session = Depends(get_db)):
    rows = db.query(AppSetting).all()
    user_key = _request_user_key(request)
    items = [
        {
            "key": row.key,
            "value": json.loads(row.value) if row.value else {}
        }
        for row in rows
        if row.key == build_setting_storage_key(row.key.split("::user::")[0], user_key) or "::user::" not in row.key
    ]
    return ok(items)


@router.get("/{key}")  # 获取单个设置
def get_setting(key: str, request: Request, db: Session = Depends(get_db)):
    user_key = _request_user_key(request)
    value = load_json_setting(db, key, default={}, user_key=user_key)
    return ok({"key": key, "value": value})


@router.put("/{key}")  # 保存单个设置
def set_setting(key: str, payload: SettingPayload, request: Request, db: Session = Depends(get_db)):
    user_key = _request_user_key(request)
    save_json_setting(db, key, payload.value, user_key=user_key)
    db.commit()
    return ok({"key": key, "value": payload.value}, "saved")
