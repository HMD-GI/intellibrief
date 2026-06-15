from .base import BaseCrawler, RawArticle  # 导入基类和数据结构
from .rss_spider import RssCrawler  # 导入 RSS 爬虫
from .web_static import StaticCrawler  # 导入静态爬虫
from .web_dynamic import DynamicCrawler  # 导入动态爬虫
from .search_aggregator import SearchAggregator  # 导入搜索聚合爬虫
from app.models.source import SourceType, Source  # 导入枚举和模型

def get_crawler(source: Source) -> BaseCrawler:  # 工厂函数，根据信息源类型返回对应的爬虫实例
    if source.source_type == SourceType.rss:  # 如果是 RSS
        return RssCrawler(source)  # 返回 RssCrawler 实例
    elif source.source_type == SourceType.static:  # 如果是静态网页
        return StaticCrawler(source)  # 返回 StaticCrawler 实例
    elif source.source_type == SourceType.dynamic:  # 如果是动态网页
        return DynamicCrawler(source)  # 返回 DynamicCrawler 实例
    elif source.source_type == SourceType.search:  # 如果是搜索聚合
        return SearchAggregator(source)  # 返回 SearchAggregator 实例
    else:  # 如果类型未知
        raise ValueError(f"Unknown source type: {source.source_type}")  # 抛出值异常
