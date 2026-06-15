from abc import ABC, abstractmethod  # 导入抽象基类及装饰器
from typing import List  # 导入 List 类型提示
from dataclasses import dataclass  # 导入 dataclass 装饰器用于快速构建数据类
from datetime import datetime  # 导入 datetime 用于时间处理
from app.models.source import Source  # 导入 Source 模型类

@dataclass  # 使用 dataclass 装饰器自动生成 __init__, __repr__ 等方法
class RawArticle:  # 定义未处理的原始文章数据结构
    url: str  # 文章链接
    title: str  # 文章标题
    raw_html: str  # 文章未清洗的原始 HTML 内容
    published_date: datetime  # 文章发布时间
    source_id: int  # 来源信息源的 ID
    article_date: str | None = None  # 文章日期字符串，格式为 YYYY-MM-DD
    image_url: str | None = None  # 文章配图 URL，优先由源专属 XPath 提取

class BaseCrawler(ABC):  # 定义爬虫基类，继承自 ABC (Abstract Base Class)
    def __init__(self, source: Source):  # 初始化方法，接收 Source 实例
        self.source = source  # 将传入的源保存为实例属性

    @abstractmethod  # 声明抽象方法，子类必须实现
    def fetch(self) -> List[RawArticle]:  # 定义抓取数据的接口
        """返回未处理的原始文章列表"""
        pass  # 抽象方法无具体实现
