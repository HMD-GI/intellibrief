import requests  # 导入 requests 库
from bs4 import BeautifulSoup  # 导入 BeautifulSoup
from typing import List  # 导入 List
from datetime import datetime  # 导入 datetime
from crawlers.base import BaseCrawler, RawArticle  # 导入基类
import logging  # 导入日志模块
from urllib.parse import urlparse, parse_qs  # 导入 URL 解析模块

logger = logging.getLogger(__name__)  # 初始化日志

class SearchAggregator(BaseCrawler):  # 搜索引擎聚合爬虫类
    def fetch(self) -> List[RawArticle]:  # 实现抓取方法
        results = []  # 初始化结果列表
        try:  # 开启异常捕获
            # 例如 source.url = "https://www.bing.com/search?q={query}"
            topics = self.source.topics.split(',') if self.source.topics else []  # 按逗号分割主题
            headers = {  # 设置请求头，伪装成浏览器
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            
            for topic in topics:  # 遍历每个关注的主题
                topic = topic.strip()  # 去除空格
                if not topic:  # 如果为空则跳过
                    continue
                
                search_url = self.source.url.format(query=topic)  # 格式化搜索 URL，填入 query
                resp = requests.get(search_url, headers=headers, timeout=10)  # 发起搜索请求
                resp.raise_for_status()  # 检查响应状态
                
                soup = BeautifulSoup(resp.text, 'html.parser')  # 解析搜索结果页面
                # 以下为针对必应 (Bing) 搜索结果的解析逻辑
                for item in soup.select('li.b_algo h2 a'):  # 选择搜索结果的标题链接
                    url = item.get('href')  # 获取链接
                    title = item.get_text(strip=True)  # 获取标题
                    
                    if not url or url.startswith('/'):  # 过滤无效或相对链接
                        continue
                        
                    # 抓取搜索结果的详情页
                    try:  # 详情页抓取异常捕获
                        detail_resp = requests.get(url, headers=headers, timeout=10)  # 请求详情页
                        raw_html = detail_resp.text if detail_resp.status_code == 200 else ""  # 保存 HTML
                    except Exception as e:  # 发生异常
                        logger.error(f"Failed to fetch detail from search result {url}: {e}")  # 记录错误
                        raw_html = ""  # 内容置空
                        
                    results.append(RawArticle(  # 添加到结果中
                        url=url,  # 链接
                        title=title,  # 标题
                        raw_html=raw_html,  # HTML 源码
                        published_date=datetime.utcnow(),  # 默认当前时间
                        source_id=self.source.id  # 关联的源 ID
                    ))
        except Exception as e:  # 最外层异常捕获
            logger.error(f"Error in search aggregator {self.source.url}: {e}")  # 记录错误
            
        return results  # 返回抓取结果
