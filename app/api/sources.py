from fastapi import APIRouter, Depends, HTTPException  # 导入 FastAPI 核心组件
from sqlalchemy.orm import Session  # 导入 SQLAlchemy Session
from typing import List  # 导入 List 类型提示
from pydantic import BaseModel, HttpUrl  # 导入 Pydantic 基类和类型
from app.database import get_db  # 导入获取数据库会话的依赖
from app.models.source import Source, SourceType  # 导入 Source 模型和枚举

router = APIRouter(prefix="/sources", tags=["sources"])  # 创建路由实例，设置前缀和标签

class SourceCreate(BaseModel):  # 定义创建信息源的请求体模型
    name: str  # 信息源名称
    source_type: SourceType  # 信息源类型（关联枚举）
    url: str  # 信息源 URL
    parser_config: dict = None  # 解析配置字典，默认为空
    topics: str = ""  # 关注主题，默认为空字符串
    is_active: bool = True  # 是否激活，默认为 True

class SourceResponse(SourceCreate):  # 定义信息源响应体模型，继承自 SourceCreate
    id: int  # 增加 id 字段

    class Config:  # Pydantic 内部配置类
        from_attributes = True  # 允许从 ORM 模型属性进行解析

@router.get("/", response_model=List[SourceResponse])  # 注册 GET 路由，获取信息源列表
def read_sources(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):  # 定义处理函数，依赖注入 db
    sources = db.query(Source).offset(skip).limit(limit).all()  # 查询数据库，支持分页
    return sources  # 返回查询结果

@router.post("/", response_model=SourceResponse)  # 注册 POST 路由，创建信息源
def create_source(source: SourceCreate, db: Session = Depends(get_db)):  # 定义处理函数，接收请求体并注入 db
    db_source = Source(**source.model_dump())  # 将请求体验证模型转为字典并实例化 ORM 模型
    db.add(db_source)  # 添加到数据库会话
    db.commit()  # 提交事务
    db.refresh(db_source)  # 刷新以获取数据库生成的 ID
    return db_source  # 返回创建的对象

@router.put("/{source_id}", response_model=SourceResponse)  # 注册 PUT 路由，更新信息源
def update_source(source_id: int, source: SourceCreate, db: Session = Depends(get_db)):  # 定义处理函数
    db_source = db.query(Source).filter(Source.id == source_id).first()  # 根据 ID 查询现有记录
    if not db_source:  # 如果没找到
        raise HTTPException(status_code=404, detail="Source not found")  # 抛出 404 错误
    for key, value in source.model_dump().items():  # 遍历请求体中的字段
        setattr(db_source, key, value)  # 更新 ORM 对象属性
    db.commit()  # 提交事务
    db.refresh(db_source)  # 刷新对象
    return db_source  # 返回更新后的对象

@router.delete("/{source_id}")  # 注册 DELETE 路由，删除信息源
def delete_source(source_id: int, db: Session = Depends(get_db)):  # 定义处理函数
    db_source = db.query(Source).filter(Source.id == source_id).first()  # 查询要删除的记录
    if not db_source:  # 如果没找到
        raise HTTPException(status_code=404, detail="Source not found")  # 抛出 404 错误
    db.delete(db_source)  # 在会话中标记删除
    db.commit()  # 提交事务
    return {"ok": True}  # 返回成功响应
