from sqlalchemy import Column, DateTime, Integer, String, Text  # 导入设置表所需列类型
import datetime  # 导入时间模块
from app.database import Base  # 导入 ORM 基类


class AppSetting(Base):  # 定义通用设置模型，用于前端绑定和定时配置
    __tablename__ = "app_settings"  # 设置表名

    id = Column(Integer, primary_key=True, index=True)  # 主键 ID
    key = Column(String, unique=True, index=True)  # 设置项 Key
    value = Column(Text, nullable=True)  # 设置项 JSON 字符串
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)  # 更新时间
