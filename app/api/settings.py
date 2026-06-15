import json  # 导入 JSON
from fastapi import APIRouter, Depends  # 导入 FastAPI 组件
from pydantic import BaseModel  # 导入 BaseModel
from sqlalchemy.orm import Session  # 导入 Session
from app.api.response import ok  # 导入统一响应函数
from app.database import get_db  # 导入数据库依赖
from app.models.setting import AppSetting  # 导入设置模型


router = APIRouter(prefix="/settings", tags=["settings"])  # 创建设置路由


class SettingPayload(BaseModel):  # 定义设置请求体
    key: str  # 设置键
    value: dict  # 设置值


@router.get("/")  # 获取所有设置
def list_settings(db: Session = Depends(get_db)):
    rows = db.query(AppSetting).all()
    items = [
        {"key": row.key, "value": json.loads(row.value) if row.value else {}}
        for row in rows
    ]
    return ok(items)


@router.get("/{key}")  # 获取单个设置
def get_setting(key: str, db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return ok({"key": key, "value": json.loads(row.value) if row and row.value else {}})


@router.put("/{key}")  # 保存单个设置
def set_setting(key: str, payload: SettingPayload, db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row:
        row = AppSetting(key=key, value=json.dumps(payload.value, ensure_ascii=False))
        db.add(row)
    else:
        row.value = json.dumps(payload.value, ensure_ascii=False)
    db.commit()
    return ok({"key": key, "value": payload.value}, "saved")
