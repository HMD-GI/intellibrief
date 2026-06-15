import requests  # 导入 requests 库发送 HTTP 请求
from bs4 import BeautifulSoup  # 导入 BeautifulSoup 库解析 HTML
from typing import List  # 导入 List 类型提示
from datetime import date, datetime  # 导入日期时间处理
from crawlers.base import BaseCrawler, RawArticle  # 导入爬虫基类和数据结构
from app.config import get_source_xpath_config  # 导入源专属 XPath 配置读取函数
import logging  # 导入日志模块
from urllib.parse import urljoin  # 导入 urljoin 拼接绝对 URL
import re  # 导入正则，用于解析中文日期字符串

logger = logging.getLogger(__name__)  # 初始化当前模块日志

def _parse_chinese_article_datetime(date_text: str) -> datetime | None:  # 解析“2026年6月11号 15:01”格式
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]\s*(\d{1,2}):(\d{1,2})", date_text or "")
    if not match:
        return None
    year, month, day, hour, minute = map(int, match.groups())
    return datetime(year, month, day, hour, minute)

def _extract_article_datetime(raw_html: str, date_xpath: str | None) -> datetime | None:  # 按配置 XPath 从详情页提取发布时间
    if not date_xpath:
        return None
    try:
        from lxml import html  # 延迟导入 lxml，避免静态初始化影响其他爬虫
        tree = html.fromstring(raw_html)
        nodes = tree.xpath(date_xpath)
        if not nodes:
            return None
        # XPath 命中的节点可能是元素或文本，统一转成干净字符串再解析
        date_text = nodes[0].text_content().strip() if hasattr(nodes[0], "text_content") else str(nodes[0]).strip()
        return _parse_chinese_article_datetime(date_text)
    except Exception as e:
        logger.warning(f"Failed to extract article date by XPath: {e}")
        return None

def _extract_article_image_url(raw_html: str, image_xpath: str | None, base_url: str) -> str | None:  # 按配置 XPath 提取文章配图 URL
    if not image_xpath:
        return None
    try:
        from lxml import html  # 延迟导入 lxml，避免影响未使用 XPath 的来源
        tree = html.fromstring(raw_html)
        nodes = tree.xpath(image_xpath)
        if not nodes:
            return None
        container = nodes[0]
        img_nodes = container.xpath(".//img") if hasattr(container, "xpath") else []
        if not img_nodes:
            return None
        img = img_nodes[0]
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
        )  # 常见图片懒加载字段
        if not src:
            return None
        src = src.strip()
        if not src or src.startswith("data:"):
            return None
        return urljoin(base_url, src)
    except Exception as e:
        logger.warning(f"Failed to extract article image by XPath: {e}")
        return None

class StaticCrawler(BaseCrawler):  # 定义静态网页爬虫类
    def fetch(self) -> List[RawArticle]:  # 实现抓取方法
        results = []  # 初始化结果列表
        try:  # 开启异常捕获
            config = self.source.parser_config or {}  # 获取源的解析配置，若为空则默认空字典
            list_selector = config.get("list_selector")  # 从配置中提取列表选择器
            link_selector = config.get("link_selector", "a")  # 提取链接选择器，默认为 a 标签
            title_selector = config.get("title_selector")  # 提取标题选择器
            xpath_config = get_source_xpath_config(self.source.url)  # 获取当前来源专属 XPath 配置
            article_date_xpath = xpath_config.get("article_date_xpath")  # 获取文章日期 XPath
            article_image_xpath = xpath_config.get("article_image_xpath")  # 获取文章图片容器 XPath
            
            if not list_selector:  # 如果没配置列表选择器
                logger.error(f"No list_selector for source {self.source.name}")  # 报错日志
                return results  # 返回空列表

            resp = requests.get(self.source.url, timeout=10)  # 发起 HTTP 请求访问列表页
            resp.raise_for_status()  # 如果响应状态码不是 200，则抛出 HTTPError
            soup = BeautifulSoup(resp.text, 'html.parser')  # 使用 BeautifulSoup 解析 HTML
            
            items = soup.select(list_selector)  # 使用列表选择器查找所有匹配的 DOM 元素

            today_str = date.today().isoformat()  # 当天日期字符串，用于过滤文章

            for item in items:  # 遍历每个条目
                link_tag = item.select_one(link_selector) if item.name != 'a' else item  # 获取链接 DOM
                if not link_tag or not link_tag.get('href'):  # 如果没找到链接或 href 属性为空
                    continue  # 跳过当前条目
                
                url = urljoin(self.source.url, link_tag['href'])  # 拼接为绝对 URL
                # 如果有标题选择器则按其提取，否则直接使用链接标签内的文本
                title = item.select_one(title_selector).get_text(strip=True) if title_selector and item.select_one(title_selector) else link_tag.get_text(strip=True)
                
                # 抓取详情页
                try:  # 开启抓取详情页异常捕获
                    detail_resp = requests.get(url, timeout=10)  # 发请求获取详情
                    raw_html = detail_resp.text if detail_resp.status_code == 200 else ""  # 如果成功则保存文本，否则为空
                except Exception as e:  # 捕获请求异常
                    logger.error(f"Failed to fetch details for {url}: {e}")  # 记录异常日志
                    raw_html = ""  # 异常时将 HTML 置空

                published_at = _extract_article_datetime(raw_html, article_date_xpath) if raw_html else None  # 从详情页提取文章发布时间
                if not published_at:
                    logger.info(f"Skip article without parsable date: {url}")
                    continue
                article_date = published_at.date().isoformat()
                if article_date != today_str:
                    logger.info(f"Skip non-today article {article_date}: {url}")
                    continue
                image_url = _extract_article_image_url(raw_html, article_image_xpath, url) if raw_html else None  # 提取源专属图片 URL

                results.append(RawArticle(  # 添加到结果列表
                    url=url,  # 设置 URL
                    title=title,  # 设置标题
                    raw_html=raw_html,  # 设置详情页 HTML
                    published_date=published_at,  # 保存详情页解析到的发布时间
                    source_id=self.source.id,  # 设置源 ID
                    article_date=article_date,  # 保存 YYYY-MM-DD 格式文章日期
                    image_url=image_url  # 保存按源专属 XPath 提取到的图片 URL
                ))
        except Exception as e:  # 捕获最外层爬取异常
            logger.error(f"Error crawling static page {self.source.url}: {e}")  # 记录异常
        
        return results  # 返回结果
