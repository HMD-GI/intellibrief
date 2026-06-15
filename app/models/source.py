from sqlalchemy import Column, Integer, String, Boolean, JSON, Enum  # 从 sqlalchemy 导入所需的列类型
import enum  # 导入 python 标准库 enum，用于枚举类
from app.database import Base  # 从 app.database 导入基类 Base

class SourceType(str, enum.Enum):  # 定义信息源类型枚举类，继承自 str 和 enum.Enum 方便序列化
    rss = "rss"  # RSS 订阅类型
    static = "static"  # 静态网页爬虫类型
    dynamic = "dynamic"  # 动态网页爬虫类型（需要渲染JS）
    search = "search"  # 搜索引擎聚合类型

class Source(Base):  # 定义 Source 数据模型，继承自 Base
    __tablename__ = "sources"  # 指定数据库中对应的表名为 sources

    id = Column(Integer, primary_key=True, index=True)  # 定义主键 ID，整数类型，并创建索引
    name = Column(String, index=True)  # 定义信息源名称列，字符串类型，并创建索引
    source_type = Column(Enum(SourceType))  # 定义信息源类型列，关联上面的 SourceType 枚举
    url = Column(String)  # 定义信息源地址列，字符串类型
    parser_config = Column(JSON, nullable=True)  # 定义解析器配置列，JSON 格式，允许为空（用于存储 CSS 选择器等配置）
    topics = Column(String) # 定义关注主题列，字符串类型（通常以逗号分隔）
    is_active = Column(Boolean, default=True)  # 定义激活状态列，布尔类型，默认为激活(True)
