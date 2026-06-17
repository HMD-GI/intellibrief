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

def _repair_briefs_table(cursor):  # ?? briefs ??????????????
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='briefs'")  # ?? briefs ?????
    briefs_exists = cursor.fetchone() is not None
    if not briefs_exists:
        return

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='briefs'")  # ??????
    create_sql_row = cursor.fetchone()
    create_sql = create_sql_row[0] if create_sql_row else ""

    cursor.execute("PRAGMA index_list(briefs)")  # ?? briefs ??????????????
    brief_indexes = cursor.fetchall()
    has_legacy_unique_date_index = False
    for index_row in brief_indexes:
        index_name = index_row[1]
        is_unique = bool(index_row[2])
        if not is_unique:
            continue
        cursor.execute(f"PRAGMA index_info({index_name})")
        index_columns = [row[2] for row in cursor.fetchall()]
        if index_columns == ["date"]:
            has_legacy_unique_date_index = True
            break

    needs_rebuild = ("UNIQUE" in create_sql.upper() and "date" in create_sql)  # ?? date ???????? DROP?????
    if needs_rebuild:
        logger.info("Rebuilding briefs table to support topic based briefs.")  # ??????
        cursor.execute("""
            CREATE TABLE briefs_new (
                id INTEGER NOT NULL PRIMARY KEY,
                date DATE,
                title VARCHAR,
                topic VARCHAR,
                brief_type VARCHAR,
                html_content TEXT,
                article_ids JSON,
                generated_at DATETIME
            )
        """)  # ??? date ???????
        cursor.execute("PRAGMA table_info(briefs)")  # ?????
        old_columns = {row[1] for row in cursor.fetchall()}
        topic_expr = "topic" if "topic" in old_columns else "'??'"
        brief_type_expr = "brief_type" if "brief_type" in old_columns else "'daily'"
        cursor.execute(f"""
            INSERT INTO briefs_new (id, date, title, topic, brief_type, html_content, article_ids, generated_at)
            SELECT id, date, title, {topic_expr}, {brief_type_expr}, html_content, article_ids, generated_at FROM briefs
        """)  # ??????????????????
        cursor.execute("DROP TABLE briefs")
        cursor.execute("ALTER TABLE briefs_new RENAME TO briefs")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_date ON briefs(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_topic ON briefs(topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_brief_type ON briefs(brief_type)")
    else:
        cursor.execute("PRAGMA table_info(briefs)")  # ?? briefs ????
        brief_columns = {row[1] for row in cursor.fetchall()}
        if "topic" not in brief_columns:
            cursor.execute("ALTER TABLE briefs ADD COLUMN topic VARCHAR")  # ???????
        if "brief_type" not in brief_columns:
            cursor.execute("ALTER TABLE briefs ADD COLUMN brief_type TEXT")  # ???????
        if has_legacy_unique_date_index:
            for index_row in brief_indexes:
                index_name = index_row[1]
                is_unique = bool(index_row[2])
                if not is_unique:
                    continue
                cursor.execute(f"PRAGMA index_info({index_name})")
                index_columns = [row[2] for row in cursor.fetchall()]
                if index_columns == ["date"]:
                    cursor.execute(f"DROP INDEX IF EXISTS {index_name}")  # ????? date ?????
                    logger.info(f"Dropped legacy unique brief index: {index_name}")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_date ON briefs(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_topic ON briefs(topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_briefs_brief_type ON briefs(brief_type)")

    cursor.execute("UPDATE briefs SET brief_type = 'daily' WHERE brief_type IS NULL OR brief_type = ''")  # ????????
    cursor.execute("UPDATE briefs SET topic = '??' WHERE topic IS NULL OR topic = ''")  # ????????

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

            _repair_briefs_table(cursor)  # 修复 briefs 表结构，支持按主题生成多份简报

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
