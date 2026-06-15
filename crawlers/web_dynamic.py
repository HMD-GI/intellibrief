from typing import List  # 导入 List
from datetime import datetime  # 导入 datetime
from crawlers.base import BaseCrawler, RawArticle  # 导入基类
import logging  # 导入日志
import asyncio  # 导入 asyncio 库处理异步
from playwright.async_api import async_playwright  # 导入 Playwright 异步 API
from bs4 import BeautifulSoup  # 导入 BeautifulSoup
from urllib.parse import urljoin  # 导入 urljoin

logger = logging.getLogger(__name__)  # 初始化日志

class DynamicCrawler(BaseCrawler):  # 动态网页爬虫类
    def fetch(self) -> List[RawArticle]:  # 暴露给 Celery 调用的同步方法
        # 因为 Playwright 是异步的，需要用 asyncio.run 运行它
        try:  # 开启异常捕获
            return asyncio.run(self._async_fetch())  # 阻塞等待异步方法执行完毕并返回
        except Exception as e:  # 捕获异常
            logger.error(f"Error in dynamic crawler for {self.source.url}: {e}")  # 记录异常日志
            return []  # 发生异常返回空列表

    async def _async_fetch(self) -> List[RawArticle]:  # 真正的异步抓取逻辑
        results = []  # 初始化结果
        config = self.source.parser_config or {}  # 获取配置
        list_selector = config.get("list_selector")  # 获取列表选择器
        link_selector = config.get("link_selector", "a")  # 获取链接选择器
        max_articles = config.get("max_articles", 5)  # 默认最多抓取 5 篇
        max_failures = config.get("max_failures", 10)  # 最大连续失败次数
        
        if not list_selector:  # 缺少列表选择器
            logger.error(f"No list_selector for source {self.source.name}")  # 报错
            return results  # 返回空列表

        async with async_playwright() as p:  # 异步启动 Playwright 实例
            # 尝试连接本地 Chrome
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    channel="chrome" # 指定使用系统自带的 Chrome 浏览器
                )
            except Exception as e:
                logger.error(f"Failed to launch built-in Chrome, please ensure Chrome is installed: {e}")
                return results

            page = await browser.new_page()  # 新建一个标签页
            items = []  # 提前初始化，防止异常时 finally 中访问未定义变量
            
            try:  # 捕获页面操作异常
                logger.info(f"Navigating to: {self.source.url}")
                await page.goto(self.source.url, wait_until="domcontentloaded", timeout=30000)  # 访问 URL，仅等待 DOM 加载完成（避免 networkidle 因第三方资源超时）
                logger.info("Page loaded successfully")
                content = await page.content()  # 获取渲染后的完整 HTML 源码
                soup = BeautifulSoup(content, 'html.parser')  # 解析 HTML
                
                items = soup.select(list_selector)[:max_articles]  # 查找列表条目并限制数量
                logger.info(f"Found {len(items)} items (limited to {max_articles})")
                
                fetch_detail = config.get("fetch_detail", True)  # 是否抓取详情页
                consecutive_failures = 0  # 连续失败计数器
                
                for idx, item in enumerate(items):  # 遍历条目
                    # 检查是否达到最大连续失败次数
                    if consecutive_failures >= max_failures:
                        logger.error(f"Reached maximum consecutive failures ({max_failures}), stopping crawl")
                        break
                    
                    try:
                        link_tag = item.select_one(link_selector) if item.name != 'a' else item  # 提取链接节点
                        if not link_tag or not link_tag.get('href'):  # 如果链接不存在
                            logger.warning(f"[{idx+1}/{len(items)}] No valid link found, skipping")
                            consecutive_failures += 1
                            continue  # 跳过
                            
                        url = urljoin(self.source.url, link_tag['href'])  # 拼接为绝对 URL
                        title = link_tag.get_text(strip=True)  # 提取标题文本
                        
                        if not title:
                            logger.warning(f"[{idx+1}/{len(items)}] Empty title, skipping")
                            consecutive_failures += 1
                            continue
                        
                        logger.info(f"[{idx+1}/{len(items)}] Processing: {title[:60]}...")
                        
                        raw_html = ""
                        if fetch_detail:
                            detail_page = await browser.new_page()  # 开启新的详情页标签
                            try:  # 捕获详情抓取异常
                                await detail_page.goto(url, timeout=30000, wait_until="domcontentloaded")  # 访问并等待 DOM 加载完成（超时 30 秒）
                                raw_html = await detail_page.content()  # 获取详情页 HTML
                                logger.info(f"Successfully fetched: {title[:50]}")
                                consecutive_failures = 0  # 成功后重置失败计数
                            except Exception as e:  # 发生异常
                                error_msg = str(e)
                                logger.error(f"Failed to fetch detail for {url}: {error_msg}")
                                logger.error(f"Failure reason: {error_msg[:200]}")
                                raw_html = ""  # 内容置空
                                consecutive_failures += 1
                            finally:  # 最终块
                                await detail_page.close()  # 务必关闭标签页以释放内存
                        else:
                            raw_html = content  # 使用列表页内容
                            consecutive_failures = 0  # 不抓取详情页时不算失败
                            
                        results.append(RawArticle(  # 添加结果
                            url=url,  # 传入 URL
                            title=title,  # 传入标题
                            raw_html=raw_html,  # 传入 HTML
                            published_date=datetime.utcnow(),  # 当前时间
                            source_id=self.source.id  # 源 ID
                        ))
                    except Exception as e:
                        logger.error(f"[{idx+1}/{len(items)}] Unexpected error processing item: {str(e)[:200]}")
                        consecutive_failures += 1
                        continue
                        
            except Exception as e:
                logger.error(f"Error fetching page {self.source.url}: {e}", exc_info=True)
            finally:  # 最终块
                await browser.close()  # 关闭浏览器实例
                
        logger.info(f"Crawl completed. Successfully fetched {len(results)} articles out of {len(items)} items")
        return results  # 返回结果列表
