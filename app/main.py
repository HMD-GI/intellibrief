import logging
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import briefs, settings, sources, tasks, weather
from app.api.response import fail
from app.config import settings as app_settings
from app.database import Base, engine, ensure_postgres_schema_updates, ensure_sqlite_schema
import app.models  # noqa: F401  # 导入全部模型，确保建表完整

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# 启动时先根据 ORM 元数据补齐缺失表，再执行历史结构修复。
Base.metadata.create_all(bind=engine)
ensure_postgres_schema_updates()
ensure_sqlite_schema()

app = FastAPI(
    title="IntelliBrief",
    description="AI 驱动的情报聚合与简报生成器",
    version="1.0.0",
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """统一处理业务层抛出的 HTTP 异常。"""

    detail = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(message=detail, code=exc.status_code, data={}),
    )


@app.exception_handler(Exception)
async def general_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """统一处理未捕获异常，避免前端拿到不一致的错误结构。"""

    logging.getLogger(__name__).exception("Unhandled application error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=fail(message="服务端内部错误，请稍后重试。", code=500, data={}),
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.frontend_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PHOTO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "photo")
os.makedirs(PHOTO_DIR, exist_ok=True)
app.mount("/photo", StaticFiles(directory=PHOTO_DIR), name="photo")

DIGEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest")
os.makedirs(DIGEST_DIR, exist_ok=True)
app.mount("/digest", StaticFiles(directory=DIGEST_DIR), name="digest")

app.include_router(sources.router)
app.include_router(briefs.router)
app.include_router(tasks.router)
app.include_router(settings.router)
app.include_router(weather.router)
tasks.restore_schedule_timer()


@app.get("/")
def root():
    """健康检查。"""

    return {"message": "Welcome to IntelliBrief API. Visit /docs for API documentation."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
