from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.response import ok
from app.database import get_db
from app.models.brief import Brief

router = APIRouter(prefix="/briefs", tags=["briefs"])


class BriefBase(BaseModel):
    """简报列表基础模型。"""

    id: int
    date: date
    title: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[BriefBase])
def read_briefs(skip: int = 0, limit: int = 30, db: Session = Depends(get_db)):
    """读取未删除的简报列表。"""

    briefs = (
        db.query(Brief)
        .filter(Brief.is_deleted == False)
        .order_by(Brief.generated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return briefs


@router.get("/query")
def query_briefs(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    brief_type: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    """按日期、类型、主题查询未删除简报。"""

    query = db.query(Brief).filter(Brief.is_deleted == False)
    if start_date:
        query = query.filter(Brief.date >= start_date)
    if end_date:
        query = query.filter(Brief.date <= end_date)
    if brief_type and brief_type != "all":
        query = query.filter(Brief.brief_type == brief_type)
    if topic and topic != "all":
        query = query.filter(Brief.topic == topic)

    total = query.count()
    briefs = query.order_by(Brief.generated_at.desc()).offset(skip).limit(limit).all()
    items = [
        {
            "id": brief.id,
            "date": brief.date.isoformat(),
            "title": brief.title,
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
            "article_count": len(brief.article_ids or []),
            "type": brief.brief_type or "daily",
            "topic": brief.topic or "综合",
            "keywords": brief.keywords or [],
            "run_key": brief.run_key,
        }
        for brief in briefs
    ]
    return ok({"items": items, "total": total})


@router.get("/item/{brief_id}/content")
def read_brief_content_by_id(brief_id: int, db: Session = Depends(get_db)):
    """按 ID 读取未删除简报内容。"""

    brief = db.query(Brief).filter(Brief.id == brief_id, Brief.is_deleted == False).first()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    return ok(
        {
            "id": brief.id,
            "date": brief.date.isoformat(),
            "title": brief.title,
            "topic": brief.topic or "综合",
            "html_content": brief.html_content,
            "article_ids": brief.article_ids or [],
            "keywords": brief.keywords or [],
            "type": brief.brief_type or "daily",
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
            "run_key": brief.run_key,
        }
    )


@router.get("/item/{brief_id}/html", response_class=HTMLResponse)
def read_brief_html_by_id(brief_id: int, db: Session = Depends(get_db)):
    """按 ID 返回未删除简报 HTML。"""

    brief = db.query(Brief).filter(Brief.id == brief_id, Brief.is_deleted == False).first()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief.html_content


@router.delete("/item/{brief_id}")
def delete_brief_by_id(brief_id: int, db: Session = Depends(get_db)):
    """按 ID 软删除简报。

    原理：
    1. 不物理删除，保留 article_ids。
    2. 这样后续再次生成时，可以优先合并被删除简报中的文章。
    """

    brief = db.query(Brief).filter(Brief.id == brief_id, Brief.is_deleted == False).first()
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    brief.is_deleted = True
    brief.deleted_at = datetime.utcnow()
    db.commit()
    return ok(True, "deleted")
