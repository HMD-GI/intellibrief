from sqlalchemy import create_engine  # 导入 create_engine，用于创建数据库引擎
from sqlalchemy.orm import sessionmaker  # 导入 sessionmaker，用于创建数据库会话工厂
from sqlalchemy.ext.declarative import declarative_base  # 导入 declarative_base，用于构建 ORM 基类
from app.config import settings  # 导入项目配置对象 settings
import logging  # 导入日志模块

# 创建数据库引擎
engine = create_engine(  # 调用 create_engine 初始化引擎
    settings.DATABASE_URL,  # 传入数据库连接 URL
    # 如果是 sqlite 数据库，需要禁用 check_same_thread 以支持多线程访问，否则传空字典
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

# 创建本地会话工厂类
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # 关闭自动提交和自动刷新，绑定引擎

# 创建声明式基类
Base = declarative_base()  # 所有 ORM 模型都将继承此基类

logger = logging.getLogger(__name__)  # 初始化日志

def ensure_sqlite_schema():  # 兼容 SQLite 的轻量级自修复 schema 函数
    """
    SQLite 下 create_all 不会自动给已有表补列。
    这里通过 PRAGMA table_info + ALTER TABLE 的方式确保关键列存在，便于快速测试迭代。
    """
    if not settings.DATABASE_URL.startswith("sqlite"):  # 非 sqlite 直接跳过
        return

    try:
        conn = engine.raw_connection()  # 获取底层 DB-API 连接
        try:
            cursor = conn.cursor()  # 创建游标
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")  # 检查 articles 表是否存在
            table_exists = cursor.fetchone() is not None  # 判断是否存在
            if not table_exists:
                return

            cursor.execute("PRAGMA table_info(articles)")  # 获取 articles 表的列信息
            existing_columns = {row[1] for row in cursor.fetchall()}  # row[1] 为列名

            if "image_no" not in existing_columns:
                cursor.execute("ALTER TABLE articles ADD COLUMN image_no INTEGER")  # 增加 image_no 列

            if "image_path" not in existing_columns:
                cursor.execute("ALTER TABLE articles ADD COLUMN image_path TEXT")  # 增加 image_path 列

            if "article_date" not in existing_columns:
                cursor.execute("ALTER TABLE articles ADD COLUMN article_date TEXT")  # 增加文章日期列，格式为 YYYY-MM-DD

            conn.commit()  # 提交变更
        finally:
            conn.close()  # 关闭连接
    except Exception as e:
        logger.error(f"ensure_sqlite_schema failed: {e}", exc_info=True)  # 记录错误，但不阻断启动

def get_db():  # 定义获取数据库会话的依赖函数
    db = SessionLocal()  # 实例化一个数据库会话
    try:  # 开启 try 块，确保发生异常时也能正确处理
        yield db  # 使用生成器将数据库会话返回给调用者
    finally:  # finally 块，确保不论是否异常都执行
        db.close()  # 关闭数据库会话，释放连接池资源
