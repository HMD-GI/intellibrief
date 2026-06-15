from sqlalchemy import Column, Integer, String, Text, Date, DateTime, JSON  # 导入所需的列类型
import datetime  # 导入 datetime 模块
from app.database import Base  # 导入 ORM 基类

class Brief(Base):  # 定义 Brief 简报数据模型
    __tablename__ = "briefs"  # 指定表名为 briefs

    id = Column(Integer, primary_key=True, index=True)  # 定义主键 ID，整型并建立索引
    date = Column(Date, unique=True, index=True)  # 定义简报所属日期，要求唯一并建立索引
    title = Column(String)  # 定义简报标题，字符串类型
    brief_type = Column(String, index=True, nullable=True)  # 定义简报类型，便于前端筛选
    html_content = Column(Text)  # 定义简报渲染后的 HTML 内容，长文本类型
    article_ids = Column(JSON) # 定义简报包含的文章 ID 列表，以 JSON 格式存储
    generated_at = Column(DateTime, default=datetime.datetime.utcnow)  # 定义简报生成时间，默认为当前 UTC 时间
