import requests  # 导入 requests 库
from bs4 import BeautifulSoup  # 导入 BeautifulSoup
from typing import List  # 导入 List
from datetime import date  # 导入 date
from crawlers.base import BaseCrawler, RawArticle  # 导入基类
import logging  # 导入日志模块
from urllib.parse import urljoin  # 导入 URL 拼接模块
from app.config import get_source_xpath_config  # 导入源专属 XPath 配置读取函数
from crawlers.web_static import _extract_article_datetime, _extract_article_image_url  # 复用详情页日期和图片提取逻辑
from processor.cleaner import extract_first_image_url  # 导入通用图片提取函数

logger = logging.getLogger(__name__)  # 初始化日志

class SearchAggregator(BaseCrawler):  # 搜索引擎聚合爬虫类
    def fetch(self) -> List[RawArticle]:  # 实现抓取方法
        results = []  # 初始化结果列表
        try:  # 开启异常捕获
            # 例如 source.url = "https://www.bing.com/search?q={query}"
            topics = self.source.topics.split(',') if self.source.topics else []  # 按逗号分割主题
            config = self.source.parser_config or {}  # 获取搜索源解析配置
            result_selector = config.get("result_selector") or config.get("list_selector") or "a[href]"  # 搜索结果容器选择器，不再写死 Bing
            link_selector = config.get("link_selector", "a")  # 搜索结果链接选择器
            title_selector = config.get("title_selector")  # 搜索结果标题选择器
            xpath_config = get_source_xpath_config(self.source.url)  # 获取源专属 XPath 配置
            article_date_xpath = config.get("article_date_xpath") or xpath_config.get("article_date_xpath")  # 详情页日期 XPath
            article_image_xpath = config.get("article_image_xpath") or xpath_config.get("article_image_xpath")  # 详情页图片 XPath
            today_str = date.today().isoformat()  # 当天日期字符串，用于过滤文章
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
                for item in soup.select(result_selector):  # 按配置选择搜索结果，不绑定具体搜索引擎
                    link_tag = item if item.name == "a" else item.select_one(link_selector)  # 获取链接节点
                    if not link_tag:
                        continue
                    href = link_tag.get('href')  # 获取链接
                    url = urljoin(search_url, href) if href else ""  # 拼接为绝对 URL
                    title_node = item.select_one(title_selector) if title_selector and item.name != "a" else None
                    title = title_node.get_text(strip=True) if title_node else link_tag.get_text(strip=True)  # 获取标题
                    
                    if not url or url.startswith('javascript:') or not title:  # 过滤无效链接
                        continue
                        
                    # 抓取搜索结果的详情页
                    try:  # 详情页抓取异常捕获
                        detail_resp = requests.get(url, headers=headers, timeout=10)  # 请求详情页
                        raw_html = detail_resp.text if detail_resp.status_code == 200 else ""  # 保存 HTML
                    except Exception as e:  # 发生异常
                        logger.error(f"Failed to fetch detail from search result {url}: {e}")  # 记录错误
                        raw_html = ""  # 内容置空
                    published_at = _extract_article_datetime(raw_html, article_date_xpath) if raw_html else None  # 从详情页解析发布时间
                    if not published_at:
                        logger.info(f"Skip search result without parsable date: {url}")
                        continue
                    article_date = published_at.date().isoformat()
                    if article_date != today_str:
                        logger.info(f"Skip non-today search result {article_date}: {url}")
                        continue
                    image_url = _extract_article_image_url(raw_html, article_image_xpath, url) if raw_html else None  # 优先按源专属 XPath 提图
                    image_url = image_url or (extract_first_image_url(raw_html, url) if raw_html else None)  # 无专属 XPath 时使用通用提图
                        
                    results.append(RawArticle(  # 添加到结果中
                        url=url,  # 链接
                        title=title,  # 标题
                        raw_html=raw_html,  # HTML 源码
                        published_date=published_at,  # 保存详情页发布时间
                        source_id=self.source.id,  # 关联的源 ID
                        article_date=article_date,  # 保存 YYYY-MM-DD 格式文章日期
                        image_url=image_url  # 保存图片 URL
                    ))
        except Exception as e:  # 最外层异常捕获
            logger.error(f"Error in search aggregator {self.source.url}: {e}")  # 记录错误
            
        return results  # 返回抓取结果
