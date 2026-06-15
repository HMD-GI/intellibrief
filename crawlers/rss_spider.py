import feedparser  # 导入 feedparser 库用于解析 RSS 订阅
import requests  # 导入 requests 库用于发送 HTTP 请求
from typing import List  # 导入 List 类型提示
from datetime import datetime  # 导入 datetime
from time import mktime  # 导入 mktime 用于时间转换
from crawlers.base import BaseCrawler, RawArticle  # 导入爬虫基类和数据结构
from app.models.source import Source  # 导入 Source 模型
import logging  # 导入日志模块

logger = logging.getLogger(__name__)  # 获取当前模块的 logger 实例

class RssCrawler(BaseCrawler):  # 定义 RSS 爬虫类，继承自 BaseCrawler
    def fetch(self) -> List[RawArticle]:  # 实现基类的 fetch 方法
        results = []  # 初始化结果列表
        try:  # 开启异常捕获块
            feed = feedparser.parse(self.source.url)  # 使用 feedparser 解析源的 URL
            for entry in feed.entries:  # 遍历解析出的所有文章条目
                url = entry.link  # 获取文章链接
                title = entry.title  # 获取文章标题
                
                # 有些 feed 直接包含 content，有些只有 summary
                raw_html = ""  # 初始化原始 HTML 为空
                if hasattr(entry, 'content'):  # 如果存在 content 属性
                    raw_html = entry.content[0].value  # 获取其值作为原始 HTML
                elif hasattr(entry, 'summary'):  # 否则如果存在 summary 属性
                    raw_html = entry.summary  # 获取 summary 作为原始 HTML
                
                # 如果没有内容，或者内容太短（不到200字符），则重新抓取原网页
                if not raw_html or len(raw_html) < 200:
                    try:  # 开启网页抓取异常捕获
                        resp = requests.get(url, timeout=10)  # 发起 HTTP GET 请求，超时设为 10 秒
                        if resp.status_code == 200:  # 如果请求成功
                            raw_html = resp.text  # 将响应文本作为原始 HTML
                    except Exception as e:  # 捕获请求异常
                        logger.error(f"Failed to fetch {url}: {e}")  # 记录抓取失败日志
                
                published_date = datetime.utcnow()  # 默认发布时间为当前 UTC 时间
                if hasattr(entry, 'published_parsed') and entry.published_parsed:  # 如果有解析好的发布时间
                    published_date = datetime.fromtimestamp(mktime(entry.published_parsed))  # 转换为 datetime 对象
                
                results.append(RawArticle(  # 将构造好的原始文章对象添加到结果列表
                    url=url,  # 传入 URL
                    title=title,  # 传入标题
                    raw_html=raw_html,  # 传入原始 HTML
                    published_date=published_date,  # 传入发布时间
                    source_id=self.source.id  # 传入所属的源 ID
                ))
        except Exception as e:  # 捕获解析 feed 的外层异常
            logger.error(f"Error parsing RSS {self.source.url}: {e}")  # 记录异常日志
        
        return results  # 返回包含抓取结果的列表
