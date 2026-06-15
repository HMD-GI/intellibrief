from fastapi import APIRouter, Depends, HTTPException, Query  # 导入 FastAPI 相关组件
from fastapi.responses import HTMLResponse  # 导入 HTMLResponse 用于返回 HTML 页面
from sqlalchemy.orm import Session  # 导入 SQLAlchemy Session
from datetime import date  # 导入 date 对象
from typing import List, Optional  # 导入类型提示
from pydantic import BaseModel  # 导入 BaseModel
from app.database import get_db  # 导入获取数据库会话的依赖
from app.models.brief import Brief  # 导入 Brief 数据模型
from app.api.response import ok  # 导入统一响应函数

router = APIRouter(prefix="/briefs", tags=["briefs"])  # 创建简报路由实例，前缀 /briefs

class BriefBase(BaseModel):  # 定义简报基础响应模型
    id: int  # 简报 ID
    date: date  # 简报日期
    title: str  # 简报标题

    class Config:  # 配置类
        from_attributes = True  # 允许从 ORM 属性解析

@router.get("/", response_model=List[BriefBase])  # 注册获取简报列表的 GET 路由
def read_briefs(skip: int = 0, limit: int = 30, db: Session = Depends(get_db)):  # 依赖注入获取 db
    briefs = db.query(Brief).order_by(Brief.date.desc()).offset(skip).limit(limit).all()  # 按日期倒序查询简报列表，支持分页
    return briefs  # 返回简报列表数据

@router.get("/query")  # 注册前端简报列表查询接口
def query_briefs(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    brief_type: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 30,
    db: Session = Depends(get_db),
):  # 根据时间范围和类型查询简报
    query = db.query(Brief)  # 初始化查询对象
    if start_date:
        query = query.filter(Brief.date >= start_date)
    if end_date:
        query = query.filter(Brief.date <= end_date)
    if brief_type and brief_type != "all":
        query = query.filter(Brief.brief_type == brief_type)  # 根据简报类型筛选

    total = query.count()
    briefs = query.order_by(Brief.date.desc()).offset(skip).limit(limit).all()
    items = [
        {
            "id": brief.id,
            "date": brief.date.isoformat(),
            "title": brief.title,
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
            "article_count": len(brief.article_ids or []),
            "type": brief.brief_type or "daily",
        }
        for brief in briefs
    ]
    return ok({"items": items, "total": total})

@router.get("/{brief_date}/content")  # 注册前端查看简报详情接口
def read_brief_content(brief_date: date, db: Session = Depends(get_db)):  # 返回统一 JSON 响应
    brief = db.query(Brief).filter(Brief.date == brief_date).first()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    return ok(
        {
            "id": brief.id,
            "date": brief.date.isoformat(),
            "title": brief.title,
            "html_content": brief.html_content,
            "article_ids": brief.article_ids or [],
            "type": brief.brief_type or "daily",
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
        }
    )

@router.delete("/{brief_date}")  # 注册删除简报接口
def delete_brief(brief_date: date, db: Session = Depends(get_db)):  # 删除指定日期简报
    brief = db.query(Brief).filter(Brief.date == brief_date).first()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    db.delete(brief)
    db.commit()
    return ok(True, "deleted")

@router.get("/{brief_date}", response_class=HTMLResponse)  # 注册获取具体某天简报 HTML 的 GET 路由
def read_brief_html(brief_date: date, db: Session = Depends(get_db)):  # 接收日期参数，注入 db
    brief = db.query(Brief).filter(Brief.date == brief_date).first()  # 根据日期查询简报记录
    if not brief:  # 如果简报不存在
        raise HTTPException(status_code=404, detail="Brief not found")  # 返回 404
    return brief.html_content  # 直接返回简报的 HTML 字符串
