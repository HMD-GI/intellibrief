import sys
import os
# 将项目根目录添加到系统路径中，以解决 "python app/main.py" 导致的 ModuleNotFoundError 问题
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # 导入 FastAPI 核心类
from fastapi.staticfiles import StaticFiles  # 导入 StaticFiles 用于处理静态文件 (当前未使用可保留)
import logging  # 导入 Python 内置的日志模块

from app.database import engine, Base, ensure_sqlite_schema  # 导入数据库引擎和 ORM 基类
from app.api import briefs, settings, sources, tasks  # 导入各个 API 路由模块
import app.models  # 导入所有 ORM 模型，确保 create_all 能创建完整表结构

# 初始化日志配置
logging.basicConfig(  # 调用 basicConfig 设置全局日志格式
    level=logging.INFO,  # 设置最低日志级别为 INFO
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"  # 设置日志输出格式：时间-模块名-级别-信息
)

# 在数据库中创建所有表
Base.metadata.create_all(bind=engine)  # 根据继承自 Base 的模型，在绑定的引擎上建表
ensure_sqlite_schema()  # 确保 SQLite 表结构包含测试需要的列（例如图片字段）

# 初始化 FastAPI 应用实例
app = FastAPI(  # 实例化 FastAPI 对象
    title="IntelliBrief",  # 设置 API 文档标题
    description="AI 驱动的情报聚合与简报生成器",  # 设置 API 文档描述
    version="1.0.0"  # 设置 API 版本号
)

# 运行时自动创建 photo 目录，并挂载为静态资源，便于周报展示图片
PHOTO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "photo")  # photo 目录的绝对路径
os.makedirs(PHOTO_DIR, exist_ok=True)  # 若目录不存在则创建
app.mount("/photo", StaticFiles(directory=PHOTO_DIR), name="photo")  # 将 /photo 映射到本地 photo 文件夹

# 运行时自动创建 digest 目录，并挂载为静态资源，便于直接访问已生成的简报文件
DIGEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest")  # digest 目录的绝对路径
os.makedirs(DIGEST_DIR, exist_ok=True)  # 若目录不存在则创建
app.mount("/digest", StaticFiles(directory=DIGEST_DIR), name="digest")  # 将 /digest 映射到本地 digest 文件夹

# 前后端分离：将纯前端静态资源挂载到 /frontend，便于本地直接访问
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")  # frontend 目录的绝对路径
os.makedirs(FRONTEND_DIR, exist_ok=True)  # 若目录不存在则创建
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")  # 将 /frontend 映射到前端目录

# 注册 API 路由
app.include_router(sources.router)  # 引入 sources 模块下的路由配置
app.include_router(briefs.router)  # 引入 briefs 模块下的路由配置
app.include_router(tasks.router)  # 引入 tasks 模块下的路由配置
app.include_router(settings.router)  # 引入 settings 模块下的路由配置

@app.get("/")  # 注册根路径的 GET 请求路由
def root():  # 定义根路径的处理函数
    return {"message": "Welcome to IntelliBrief API. Visit /docs for API documentation."}  # 返回欢迎信息及文档提示

if __name__ == "__main__":  # 如果直接运行此脚本
    import uvicorn  # 导入 uvicorn ASGI 服务器
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)  # 启动服务，监听所有 IP 的 8000 端口，并开启热重载
