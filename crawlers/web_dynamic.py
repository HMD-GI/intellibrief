from typing import List  # 导入 List
from datetime import date  # 导入 date
from lxml import html  # 导入 lxml.html，用于按 XPath 提取正文节点
from crawlers.base import BaseCrawler, RawArticle  # 导入基类
import logging  # 导入日志
import asyncio  # 导入 asyncio 库处理异步
import json  # 导入 JSON，用于解析动态接口返回
import random  # 导入随机数，用于反爬场景下的轻微随机等待
import re  # 导入正则，用于从页面脚本中兜底提取文章链接
import requests  # 导入 requests，用于拉取动态页面脚本兜底解析
from playwright.async_api import async_playwright  # 导入 Playwright 异步 API
from bs4 import BeautifulSoup  # 导入 BeautifulSoup
from urllib.parse import urljoin  # 导入 urljoin
from app.config import get_source_xpath_config  # 导入源专属 XPath 配置读取函数
from crawlers.web_static import _extract_article_datetime, _extract_article_image_url, _parse_article_datetime  # 复用静态爬虫的详情页日期和图片提取逻辑

logger = logging.getLogger(__name__)  # 初始化日志

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)  # 默认浏览器 UA，降低动态站点反爬识别概率

def _merge_dynamic_config(source_config: dict, xpath_config: dict) -> dict:  # 合并通用解析配置和源专属动态配置
    merged = dict(xpath_config.get("dynamic") or {})  # 先读取源专属动态配置
    merged.update(source_config or {})  # 前端录入的 parser_config 优先级更高
    for key in ("item_xpath", "article_id_regex", "date_parser"):
        if (xpath_config.get("dynamic") or {}).get(key):
            merged[key] = xpath_config["dynamic"][key]  # 源专属关键规则优先，避免旧 parser_config 覆盖导致失效
    for key in ("article_title_xpath", "article_date_xpath", "article_image_xpath", "article_content_xpath", "article_section_xpath"):
        if xpath_config.get(key):
            merged.setdefault(key, xpath_config[key])
    for key in ("article_title_selector", "article_date_selector", "article_image_selector", "article_content_selector"):
        if xpath_config.get(key):
            merged.setdefault(key, xpath_config[key])
    return merged

def _is_valid_article_url(url: str, config: dict) -> bool:  # 判断列表链接是否是真实文章链接
    if not url:
        return False
    allowed_prefixes = config.get("allowed_article_url_prefixes") or []
    if allowed_prefixes and not any(url.startswith(prefix) for prefix in allowed_prefixes):
        return False
    article_id_regex = config.get("article_id_regex")
    if not article_id_regex:
        return True
    path = url.split("?", 1)[0].rstrip("/")
    article_id = path.rsplit("/", 1)[-1]
    return bool(re.fullmatch(article_id_regex, article_id))

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
        xpath_config = get_source_xpath_config(self.source.url)  # 获取当前来源专属 XPath 配置
        config = _merge_dynamic_config(self.source.parser_config or {}, xpath_config)  # 合并动态配置，便于后续新增站点
        list_selector = config.get("list_selector")  # 获取列表选择器
        link_selector = config.get("link_selector", "a")  # 获取链接选择器
        max_failures = config.get("max_failures", 10)  # 最大连续失败次数
        article_title_xpath = config.get("article_title_xpath") or xpath_config.get("article_title_xpath")  # 获取文章标题 XPath
        article_date_xpath = config.get("article_date_xpath") or xpath_config.get("article_date_xpath")  # 获取文章日期 XPath
        article_image_xpath = config.get("article_image_xpath") or xpath_config.get("article_image_xpath")  # 获取文章图片 XPath
        article_content_xpath = config.get("article_content_xpath") or xpath_config.get("article_content_xpath")  # 获取文章正文 XPath
        article_section_xpath = config.get("article_section_xpath") or xpath_config.get("article_section_xpath")  # 获取文章正文 section XPath
        article_title_selector = config.get("article_title_selector") or xpath_config.get("article_title_selector")  # 获取文章标题 CSS 选择器
        article_date_selector = config.get("article_date_selector") or xpath_config.get("article_date_selector")  # 获取文章日期 CSS 选择器
        article_image_selector = config.get("article_image_selector") or xpath_config.get("article_image_selector")  # 获取文章图片 CSS 选择器
        article_content_selector = config.get("article_content_selector") or xpath_config.get("article_content_selector")  # 获取文章正文 CSS 选择器
        date_parser = config.get("date_parser") or xpath_config.get("date_parser")  # 获取日期解析器名称
        today_str = date.today().isoformat()  # 当天日期字符串，用于过滤文章
        
        if not list_selector:  # 缺少列表选择器
            logger.error(f"No list_selector for source {self.source.name}")  # 报错
            return results  # 返回空列表

        async with async_playwright() as p:  # 异步启动 Playwright 实例
            # 尝试连接本地 Chrome
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    channel="chrome" # 指定使用系统自带的 Chrome 浏览器
                )
            except Exception as e:
                logger.error(f"Failed to launch built-in Chrome, please ensure Chrome is installed: {e}")
                return results

            context = await browser.new_context(
                user_agent=config.get("user_agent", DEFAULT_USER_AGENT),  # 设置真实 UA，降低反爬命中率
                viewport=config.get("viewport", {"width": 1366, "height": 768}),  # 设置常见桌面分辨率
                locale=config.get("locale", "zh-CN"),  # 设置中文环境
                timezone_id=config.get("timezone_id", "Asia/Shanghai"),  # 设置中国时区
            )
            if config.get("anti_detection", True):
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")  # 隐藏 webdriver 标记
            page = await context.new_page()  # 新建一个标签页
            items = []  # 提前初始化，防止异常时 finally 中访问未定义变量
            captured_texts = []  # 保存列表页加载期间可能包含文章数据的网络响应
            captured_api_items = []  # 保存直接从网络接口解析出的文章列表候选

            async def capture_response(response):  # 捕获动态接口或脚本响应，DOM 提取失败时兜底解析
                if not config.get("capture_network", False):
                    return
                response_url = response.url
                keywords = config.get("capture_url_keywords") or []
                if keywords and not any(keyword in response_url for keyword in keywords):
                    return
                try:
                    content_type = response.headers.get("content-type", "")
                    if not any(token in content_type for token in ("json", "javascript", "text", "html")):
                        return
                    if not any(token in response_url.lower() for token in ("/api/", "list", "news", "article", "feed", "world", "huanqiu")):
                        return
                    text = await response.text()
                    if "/api/list" in response_url.lower():
                        api_items = self._extract_items_from_json_text(text, config)
                        if api_items:
                            captured_api_items.extend(api_items)
                            logger.info(f"Captured {len(api_items)} items from api/list: {response_url[:160]}")
                    if self._text_may_contain_articles(text, config):
                        captured_texts.append(text)
                        logger.info(f"Captured article-like response: {response_url[:160]}")
                except Exception as e:
                    logger.debug(f"Capture response failed for {response_url}: {e}")

            page.on("response", capture_response)
            
            try:  # 捕获页面操作异常
                logger.info(f"Navigating to: {self.source.url}")
                await page.goto(self.source.url, wait_until="domcontentloaded", timeout=30000)  # 访问 URL，仅等待 DOM 加载完成（避免 networkidle 因第三方资源超时）
                wait_selector = config.get("wait_selector")  # 可配置等待列表页关键元素
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=config.get("wait_selector_timeout", 10000))  # 等待动态列表出现
                    except Exception as e:
                        logger.warning(f"Wait selector failed for {wait_selector}: {e}")
                initial_wait_ms = int(config.get("initial_wait_ms", 0) or 0)
                if initial_wait_ms:
                    await page.wait_for_timeout(initial_wait_ms)  # 部分动态站点首屏数据晚于 domcontentloaded 注入
                await self._scroll_page(page, config)  # 对无限滚动页面执行滚动加载
                logger.info("Page loaded successfully")
                content = await page.content()  # 获取渲染后的完整 HTML 源码
                items = self._dedupe_items(captured_api_items)
                if items:
                    logger.info(f"Extracted {len(items)} items from captured api/list responses")
                if not items:
                    items = await self._extract_list_items(page, content, list_selector, config)  # 从普通 DOM、Shadow DOM 或脚本文本提取列表项
                if not items:
                    items = self._extract_items_from_captured_texts(captured_texts, config)
                    if items:
                        logger.info(f"Extracted {len(items)} items from captured network responses")
                if not items and config.get("fetch_scripts_fallback", True):
                    items = await self._extract_items_from_page_scripts(page, config)
                    if items:
                        logger.info(f"Extracted {len(items)} items from page scripts")
                items = self._filter_list_items(items, config, today_str, date_parser)
                max_items = config.get("max_items")  # 可选：限制列表页最多处理条数
                if max_items:
                    items = items[:int(max_items)]
                logger.info(f"Found {len(items)} items")
                if not items:
                    await self._log_list_diagnostics(page, config)
                    logger.warning(f"No list items found. page_title={await page.title()} current_url={page.url}")  # 记录页面状态，辅助判断反爬或选择器问题
                
                fetch_detail = config.get("fetch_detail", True)  # 是否抓取详情页
                consecutive_failures = 0  # 连续失败计数器
                seen_urls = set()  # 记录已处理 URL，避免无限滚动后重复抓取
                
                for idx, item in enumerate(items):  # 遍历条目
                    # 检查是否达到最大连续失败次数
                    if consecutive_failures >= max_failures:
                        logger.error(f"Reached maximum consecutive failures ({max_failures}), stopping crawl")
                        break
                    
                    try:
                        url = item.get("url")  # 提取链接
                        if not url:
                            logger.warning(f"[{idx+1}/{len(items)}] No valid link found, skipping")
                            consecutive_failures += 1
                            continue  # 跳过
                            
                        url = item.get("url")  # 列表预过滤阶段已规范化为绝对 URL
                        if not _is_valid_article_url(url, config):
                            logger.info(f"Skip invalid article link: {url}")
                            continue
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        title = item.get("title") or url  # 提取标题文本
                        
                        if not title:
                            logger.warning(f"[{idx+1}/{len(items)}] Empty title, skipping")
                            consecutive_failures += 1
                            continue

                        list_published_at = _parse_article_datetime(item.get("date_text") or "", date_parser)
                        if config.get("require_list_date") and not list_published_at:
                            logger.info(f"Skip article without list date: {url}")
                            continue
                        if list_published_at and list_published_at.date().isoformat() != today_str:
                            logger.info(f"Skip non-today list article {list_published_at.date().isoformat()}: {url}")
                            continue
                        
                        logger.info(f"[{idx+1}/{len(items)}] Processing: {title[:60]}...")
                        
                        raw_html = ""
                        detail_raw_html = ""
                        detail_page = None  # 详情页对象，提取日期和图片后再关闭
                        if fetch_detail:
                            detail_page = await context.new_page()  # 开启新的详情页标签
                            try:  # 捕获详情抓取异常
                                await detail_page.goto(url, timeout=30000, wait_until="domcontentloaded")  # 访问并等待 DOM 加载完成（超时 30 秒）
                                # 对已知可从源码或模板文本中抽取正文的站点，直接跳过前置等待。
                                if not config.get("skip_detail_section_wait", False):
                                    section_ready = await self._wait_for_article_section(
                                        detail_page,
                                        article_section_xpath,
                                        timeout_ms=config.get("detail_content_wait_timeout", 3000),
                                    )
                                    if not section_ready:
                                        logger.info(f"Detail article section not detected within wait window, continue extraction: {url}")
                                detail_wait_ms = config.get("wait_after_detail_ms")
                                if detail_wait_ms is None:
                                    detail_wait_ms = random.randint(400, 900)
                                detail_wait_ms = int(detail_wait_ms or 0)
                                if detail_wait_ms > 0:
                                    # 仅在配置要求时补充等待，避免正文已可提取时继续阻塞。
                                    await detail_page.wait_for_timeout(detail_wait_ms)
                                detail_raw_html = await detail_page.content()  # 获取详情页完整 HTML，用于日期和图片兜底
                                raw_html = await self._extract_content_html_from_page(
                                    detail_page,
                                    detail_raw_html,
                                    article_content_xpath,
                                    article_section_xpath,
                                    article_content_selector,
                                    url,
                                ) or detail_raw_html  # 优先保存正文容器 HTML，失败时回退完整 HTML
                                detail_title = await self._extract_text_from_page(
                                    detail_page,
                                    detail_raw_html,
                                    article_title_xpath,
                                    article_title_selector,
                                )
                                if detail_title:
                                    title = detail_title
                                logger.info(f"Successfully fetched: {title[:50]}")
                                consecutive_failures = 0  # 成功后重置失败计数
                            except Exception as e:  # 发生异常
                                error_msg = str(e)
                                logger.error(f"Failed to fetch detail for {url}: {error_msg}")
                                logger.error(f"Failure reason: {error_msg[:200]}")
                                raw_html = ""  # 内容置空
                                consecutive_failures += 1
                        else:
                            raw_html = content  # 使用列表页内容
                            detail_raw_html = content
                            detail_page = page  # 不抓详情时复用列表页
                            consecutive_failures = 0  # 不抓取详情页时不算失败

                        if fetch_detail and not raw_html:
                            if detail_page:
                                await detail_page.close()
                            continue

                        published_at = list_published_at
                        if not published_at:
                            published_at = await self._extract_datetime_from_page(
                                detail_page if fetch_detail else page,
                                detail_raw_html or raw_html,
                                article_date_xpath,
                                article_date_selector,
                                date_parser,
                            ) if raw_html else None  # 从详情页解析发布时间
                        if not published_at:
                            logger.info(f"Skip article without parsable date: {url}")
                            if fetch_detail and detail_page:
                                await detail_page.close()
                            continue
                        article_date = published_at.date().isoformat()
                        if article_date != today_str:
                            logger.info(f"Skip non-today article {article_date}: {url}")
                            if fetch_detail and detail_page:
                                await detail_page.close()
                            continue
                        image_url = await self._extract_image_from_page(
                            detail_page if fetch_detail else page,
                            detail_raw_html or raw_html,
                            article_image_xpath,
                            article_image_selector,
                            url,
                        ) if raw_html else None  # 提取源专属图片 URL
                            
                        results.append(RawArticle(  # 添加结果
                            url=url,  # 传入 URL
                            title=title,  # 传入标题
                            raw_html=raw_html,  # 传入 HTML
                            published_date=published_at,  # 保存详情页发布时间
                            source_id=self.source.id,  # 源 ID
                            article_date=article_date,  # 保存 YYYY-MM-DD 格式文章日期
                            image_url=image_url  # 保存详情页图片 URL
                        ))
                        if fetch_detail and detail_page:
                            await detail_page.close()  # 单篇处理完成后关闭详情页，释放内存
                    except Exception as e:
                        logger.error(f"[{idx+1}/{len(items)}] Unexpected error processing item: {str(e)[:200]}")
                        try:
                            if fetch_detail and detail_page:
                                await detail_page.close()  # 异常时也关闭详情页
                        except Exception:
                            pass
                        consecutive_failures += 1
                        continue
                        
            except Exception as e:
                logger.error(f"Error fetching page {self.source.url}: {e}", exc_info=True)
            finally:  # 最终块
                await context.close()  # 关闭上下文
                await browser.close()  # 关闭浏览器实例
                
        logger.info(f"Crawl completed. Successfully fetched {len(results)} articles out of {len(items)} items")
        return results  # 返回结果列表

    async def _extract_list_items(self, page, content: str, list_selector: str, config: dict) -> list[dict]:  # 提取列表页文章链接
        item_selector = config.get("item_selector")
        if item_selector:
            items = await self._extract_items_with_playwright_locators(page, config)
            if items:
                logger.info(f"Extracted {len(items)} configured items from Playwright locators")
                return items

            items = await self._extract_configured_items_from_browser(page, config)
            if items:
                logger.info(f"Extracted {len(items)} configured items from browser DOM")
                return items

        items = await self._extract_items_from_browser(page, list_selector, config)  # 优先从浏览器真实 DOM 和 Shadow DOM 提取
        if items:
            logger.info(f"Extracted {len(items)} items from browser DOM")
            return items

        soup = BeautifulSoup(content, 'html.parser')  # 解析普通 HTML
        parsed_items = []
        link_selector = config.get("link_selector", "a")
        title_selector = config.get("title_selector")
        for item in soup.select(list_selector):
            link_tag = item.select_one(link_selector) if item.name != "a" else item
            if not link_tag or not link_tag.get("href"):
                continue
            if not _is_valid_article_url(link_tag.get("href"), config):
                continue
            title_node = item.select_one(title_selector) if title_selector and item.name != "a" else None
            date_selector = config.get("date_selector")
            date_node = item.select_one(date_selector) if date_selector and item.name != "a" else None
            parsed_items.append({
                "url": link_tag.get("href"),
                "title": title_node.get_text(strip=True) if title_node else link_tag.get_text(strip=True),
                "date_text": date_node.get_text(" ", strip=True) if date_node else None,
            })
        if parsed_items:
            logger.info(f"Extracted {len(parsed_items)} items from static HTML")
            return parsed_items

        js_items = await self._extract_items_from_js_variable(page, config)  # 从 JS 全局变量和自定义元素属性中提取文章
        if js_items:
            logger.info(f"Extracted {len(js_items)} items from JS variables or custom elements")
            return js_items

        fallback_items = self._extract_items_from_text(content, config)  # 最后从脚本或内联 JSON 里提取 URL
        if fallback_items:
            logger.info(f"Extracted {len(fallback_items)} items from page text fallback")
        return fallback_items

    def _dedupe_items(self, items: list[dict]) -> list[dict]:  # 按 URL 去重保留顺序
        deduped = []
        seen = set()
        for item in items or []:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(item)
        return deduped

    def _filter_list_items(self, items: list[dict], config: dict, today_str: str, date_parser: str | None) -> list[dict]:  # 统一过滤列表候选
        filtered = []
        seen = set()
        skipped_invalid = 0
        skipped_no_date = 0
        skipped_old = 0
        require_list_date = bool(config.get("require_list_date"))
        for item in items or []:
            url = urljoin(self.source.url, item.get("url") or "")
            if not _is_valid_article_url(url, config):
                skipped_invalid += 1
                continue
            if url in seen:
                continue
            date_text = item.get("date_text") or ""
            parsed = _parse_article_datetime(date_text, date_parser)
            if require_list_date and not parsed:
                skipped_no_date += 1
                continue
            if parsed and parsed.date().isoformat() != today_str:
                skipped_old += 1
                continue
            seen.add(url)
            filtered.append({
                "url": url,
                "title": item.get("title") or url,
                "date_text": date_text,
            })
        logger.info(
            f"List filter result: kept={len(filtered)}, invalid_or_external={skipped_invalid}, "
            f"missing_date={skipped_no_date}, non_today={skipped_old}"
        )
        return filtered

    async def _extract_items_with_playwright_locators(self, page, config: dict) -> list[dict]:  # 用 Playwright locator 提取，可穿透开放 Shadow DOM
        items = []
        seen = set()
        item_selector = config.get("item_selector")
        link_selector = config.get("link_selector", "a[href]")
        title_selector = config.get("title_selector")
        date_selector = config.get("date_selector")
        if not item_selector:
            return items
        try:
            locator = page.locator(item_selector)
            count = await locator.count()
            for index in range(count):
                item = locator.nth(index)
                link = item.locator(link_selector).first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href")
                href = urljoin(self.source.url, href or "")
                if not href or not _is_valid_article_url(href, config) or href in seen:
                    continue
                seen.add(href)
                title = ""
                if title_selector:
                    title_node = item.locator(title_selector).first
                    if await title_node.count() > 0:
                        title = (await title_node.inner_text()).strip()
                if not title:
                    title = (await link.inner_text()).strip()
                date_text = ""
                if date_selector:
                    date_node = item.locator(date_selector).first
                    if await date_node.count() > 0:
                        date_text = (await date_node.inner_text()).strip()
                items.append({
                    "url": href,
                    "title": self._clean_title(title),
                    "date_text": self._clean_title(date_text),
                })
            return items
        except Exception as e:
            logger.debug(f"Playwright locator item extraction failed: {e}")
            return []

    async def _log_list_diagnostics(self, page, config: dict) -> None:  # 记录列表提取诊断信息，便于定位动态页面结构变化
        try:
            item_selector = config.get("item_selector") or ".feed-item"
            link_selector = config.get("link_selector") or "a[href*='/article/']"
            item_count = await page.locator(item_selector).count()
            link_count = await page.locator(link_selector).count()
            feed_text_count = await page.locator("text=feed-item").count()
            logger.warning(
                f"List diagnostics: item_selector={item_selector} count={item_count}, "
                f"link_selector={link_selector} count={link_count}, text_feed_item_count={feed_text_count}"
            )
        except Exception as e:
            logger.debug(f"List diagnostics failed: {e}")

    async def _extract_configured_items_from_browser(self, page, config: dict) -> list[dict]:  # 按配置的条目容器提取动态列表
        try:
            return await page.evaluate(
                """
                ({config, baseUrl}) => {
                    const results = [];
                    const seen = new Set();
                    const itemXPath = config.item_xpath;
                    const itemSelector = config.item_selector;
                    const linkSelector = config.link_selector || 'a[href]';
                    const titleSelector = config.title_selector;
                    const dateSelector = config.date_selector;
                    const articleIdRegex = config.article_id_regex ? new RegExp(config.article_id_regex) : null;
                    const allowedPrefixes = config.allowed_article_url_prefixes || [];
                    const absolutize = (href) => {
                        try { return new URL(href, baseUrl).href; } catch (e) { return ''; }
                    };

                    const clean = (value) => (value || '').toString().replace(/\\s+/g, ' ').trim();
                    const isValidArticleUrl = (href) => {
                        if (!href) return false;
                        if (allowedPrefixes.length && !allowedPrefixes.some((prefix) => href.startsWith(prefix))) return false;
                        if (!articleIdRegex) return true;
                        const path = href.split('?')[0].replace(/\\/$/, '');
                        const articleId = path.split('/').pop();
                        return articleIdRegex.test(articleId);
                    };
                    const pushItem = (item) => {
                        const link = item.matches && item.matches(linkSelector) ? item : item.querySelector(linkSelector);
                        if (!link) return;
                        const href = absolutize(link.getAttribute('href') || '');
                        if (!isValidArticleUrl(href) || seen.has(href)) return;
                        seen.add(href);
                        const titleNode = titleSelector ? item.querySelector(titleSelector) : null;
                        const dateNode = dateSelector ? item.querySelector(dateSelector) : null;
                        results.push({
                            url: href,
                            title: clean(titleNode ? titleNode.textContent : link.textContent),
                            date_text: clean(dateNode ? dateNode.textContent : '')
                        });
                    };
                    const queryXPath = (xpath, root) => {
                        const doc = root && root.ownerDocument ? root.ownerDocument : document;
                        const contextNode = root || document;
                        const nodes = [];
                        try {
                            const snapshot = doc.evaluate(xpath, contextNode, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                            for (let i = 0; i < snapshot.snapshotLength; i++) nodes.push(snapshot.snapshotItem(i));
                        } catch (e) {}
                        return nodes;
                    };
                    const roots = itemXPath ? queryXPath(itemXPath, document) : [];
                    roots.forEach((root) => {
                        if (root && root.querySelectorAll && itemSelector) root.querySelectorAll(itemSelector).forEach(pushItem);
                    });
                    document.querySelectorAll('channel-container-template, sketch-feed-template, layout-bd-template').forEach((root) => {
                        if (root.querySelectorAll) root.querySelectorAll('.feed-item.feed-item-a, .feed-item.feed-item-b, .feed-item').forEach(pushItem);
                        if (root.shadowRoot) root.shadowRoot.querySelectorAll('.feed-item.feed-item-a, .feed-item.feed-item-b, .feed-item').forEach(pushItem);
                    });
                    const walk = (root) => {
                        if (!root || !root.querySelectorAll) return;
                        root.querySelectorAll(itemSelector).forEach(pushItem);
                        root.querySelectorAll('*').forEach((node) => {
                            if (node.shadowRoot) walk(node.shadowRoot);
                        });
                    };
                    if (!results.length) walk(document);
                    return results;
                }
                """,
                {"config": config, "baseUrl": self.source.url},
            )  # 支持普通 DOM 和开放 Shadow DOM 中的“条目容器 + 链接 + 标题 + 时间”配置
        except Exception as e:
            logger.debug(f"Configured browser item extraction failed: {e}")
            return []

    async def _extract_items_from_browser(self, page, selector: str, config: dict) -> list[dict]:  # 从浏览器 DOM 递归扫描文章链接，包含 Shadow DOM
        try:
            return await page.evaluate(
                """
                ({selector, articleIdRegexText, allowedPrefixes, baseUrl}) => {
                    const results = [];
                    const seen = new Set();
                    const articleIdRegex = articleIdRegexText ? new RegExp(articleIdRegexText) : null;
                    const absolutize = (href) => {
                        try { return new URL(href, baseUrl).href; } catch (e) { return ''; }
                    };
                    const isValidArticleUrl = (href) => {
                        if (!href) return false;
                        if (allowedPrefixes.length && !allowedPrefixes.some((prefix) => href.startsWith(prefix))) return false;
                        if (!articleIdRegex) return true;
                        const path = href.split('?')[0].replace(/\\/$/, '');
                        const articleId = path.split('/').pop();
                        return articleIdRegex.test(articleId);
                    };
                    const pushLink = (node) => {
                        if (!node || !node.getAttribute) return;
                        const href = absolutize(node.getAttribute('href') || '');
                        if (!isValidArticleUrl(href) || seen.has(href)) return;
                        seen.add(href);
                        const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                        results.push({url: href, title: text});
                    };
                    const walk = (root) => {
                        if (!root || !root.querySelectorAll) return;
                        root.querySelectorAll(selector).forEach(pushLink);
                        root.querySelectorAll('*').forEach((node) => {
                            if (node.shadowRoot) walk(node.shadowRoot);
                        });
                    };
                    walk(document);
                    return results;
                }
                """,
                {
                    "selector": selector,
                    "articleIdRegexText": config.get("article_id_regex"),
                    "allowedPrefixes": config.get("allowed_article_url_prefixes") or [],
                    "baseUrl": self.source.url,
                },
            )  # 兼容普通 DOM 和开放 Shadow DOM
        except Exception as e:
            logger.debug(f"Browser list extraction failed: {e}")
            return []

    def _extract_items_from_text(self, content: str, config: dict) -> list[dict]:  # 从页面文本兜底提取文章链接
        feed_items = self._extract_feed_items_from_html_text(content, config)
        if feed_items:
            return feed_items
        json_items = self._extract_items_from_json_text(content, config)
        if json_items:
            return json_items
        huanqiu_items = self._extract_huanqiu_items_from_text(content, config)  # 专门解析环球网页面脚本中的文章数据
        if huanqiu_items:
            return huanqiu_items
        pattern = config.get("url_regex") or r"https?:\\/\\/world\.huanqiu\.com\\/article\\/[A-Za-z0-9]+|https?://world\.huanqiu\.com/article/[A-Za-z0-9]+|/article/[A-Za-z0-9]+"
        matches = re.findall(pattern, content or "")
        items = []
        seen = set()
        for match in matches:
            url = match.replace("\\/", "/") if isinstance(match, str) else match[0]
            url = urljoin(self.source.url, url)
            if not _is_valid_article_url(url, config):
                continue
            if url in seen:
                continue
            seen.add(url)
            items.append({"url": url, "title": url})
        return items

    def _extract_items_from_json_text(self, content: str, config: dict) -> list[dict]:  # 从 JSON/JSONP 接口文本递归提取文章
        text = (content or "").strip()
        if not text:
            return []
        candidates = [text]
        jsonp_match = re.search(r"^[\w.$]+\(([\s\S]*)\)\s*;?$", text)
        if jsonp_match:
            candidates.append(jsonp_match.group(1))

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except Exception:
                continue
            items = []
            seen = set()

            def normalize_url(value):
                if value is None:
                    return ""
                raw = str(value).replace("\\/", "/").strip()
                if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("/article/"):
                    return urljoin(self.source.url, raw)
                if re.fullmatch(config.get("article_id_regex") or r"(?=.*\d)[A-Za-z0-9]{6,}", raw):
                    return f"https://world.huanqiu.com/article/{raw}"
                return ""

            def walk(obj):
                if isinstance(obj, list):
                    for entry in obj:
                        walk(entry)
                    return
                if not isinstance(obj, dict):
                    return
                url = normalize_url(
                    obj.get("url")
                    or obj.get("href")
                    or obj.get("link")
                    or obj.get("articleUrl")
                    or obj.get("article_url")
                    or obj.get("articleId")
                    or obj.get("ARTICLE_ID")
                    or obj.get("aid")
                    or obj.get("id")
                )
                title = (
                    obj.get("title")
                    or obj.get("TITLE")
                    or obj.get("name")
                    or obj.get("headLine")
                    or obj.get("head_line")
                    or obj.get("summaryTitle")
                    or obj.get("articleTitle")
                    or obj.get("headline")
                )
                date_text = (
                    obj.get("time")
                    or obj.get("date")
                    or obj.get("ctime")
                    or obj.get("displayTime")
                    or obj.get("display_time")
                    or obj.get("publishDate")
                    or obj.get("publishTime")
                    or obj.get("publish_time")
                    or obj.get("pubtime")
                    or obj.get("createdAt")
                )
                if url and _is_valid_article_url(url, config) and url not in seen:
                    seen.add(url)
                    items.append({
                        "url": url,
                        "title": self._clean_title(str(title or url)),
                        "date_text": self._clean_title(str(date_text or "")),
                    })
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        walk(value)

            walk(data)
            if items:
                return items
        return []

    def _text_may_contain_articles(self, text: str, config: dict) -> bool:  # 判断响应文本是否值得进入文章提取兜底
        if not text:
            return False
        return (
            "/article/" in text
            or "feed-item" in text
            or bool(re.search(config.get("article_id_regex") or r"(?=.*\d)[A-Za-z0-9]{6,}", text))
        )

    def _extract_items_from_captured_texts(self, texts: list[str], config: dict) -> list[dict]:  # 从网络响应文本集合提取文章
        items = []
        seen = set()
        for text in texts:
            for item in self._extract_items_from_text(text, config):
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                items.append(item)
        return items

    async def _extract_items_from_page_scripts(self, page, config: dict) -> list[dict]:  # 拉取页面脚本并从脚本内容提取文章
        try:
            script_urls = await page.evaluate("""
                () => Array.from(document.querySelectorAll('script[src]'))
                    .map((node) => node.src)
                    .filter(Boolean)
            """)
        except Exception as e:
            logger.debug(f"Read page scripts failed: {e}")
            return []

        headers = {"User-Agent": config.get("user_agent", DEFAULT_USER_AGENT)}
        texts = []
        for script_url in script_urls[: int(config.get("max_script_fetch", 30))]:
            if "huanqiu" not in script_url and "world" not in script_url:
                continue
            try:
                response = requests.get(script_url, headers=headers, timeout=10)
                if response.ok and self._text_may_contain_articles(response.text, config):
                    texts.append(response.text)
                    logger.info(f"Fetched article-like script: {script_url[:160]}")
            except Exception as e:
                logger.debug(f"Fetch script failed {script_url}: {e}")
        return self._extract_items_from_captured_texts(texts, config)

    def _extract_feed_items_from_html_text(self, content: str, config: dict) -> list[dict]:  # 解析 feed-item HTML 片段
        if not content or "feed-item" not in content:
            return []
        text = content.replace("\\/", "/")
        soup = BeautifulSoup(text, "html.parser")
        items = []
        seen = set()
        for item in soup.select(".feed-item.feed-item-a, .feed-item.feed-item-b, .feed-item"):
            link_tag = item.select_one("a[href*='/article/']")
            if not link_tag:
                continue
            url = urljoin(self.source.url, link_tag.get("href"))
            if not _is_valid_article_url(url, config) or url in seen:
                continue
            seen.add(url)
            title_node = item.select_one("h4")
            date_node = item.select_one(".tool .time, .time")
            items.append({
                "url": url,
                "title": self._clean_title(title_node.get_text(" ", strip=True) if title_node else link_tag.get_text(" ", strip=True)),
                "date_text": self._clean_title(date_node.get_text(" ", strip=True) if date_node else ""),
            })
        return items

    def _extract_huanqiu_items_from_text(self, content: str, config: dict) -> list[dict]:  # 解析环球网 ARTICLE_ID + title 脚本数据
        text = (content or "").replace("\\/", "/")
        patterns = [
            r'["\'](?:articleId|ARTICLE_ID|aid|id)["\']\s*[:=]\s*["\']([A-Za-z0-9]+)["\'][\s\S]{0,500}?["\'](?:title|TITLE)["\']\s*[:=]\s*["\']([^"\']{4,160})["\']',
            r'["\'](?:title|TITLE)["\']\s*[:=]\s*["\']([^"\']{4,160})["\'][\s\S]{0,500}?["\'](?:articleId|ARTICLE_ID|aid|id)["\']\s*[:=]\s*["\']([A-Za-z0-9]+)["\']',
            r'([A-Za-z0-9]{5,})[\s\S]{0,80}?article[\s\S]{0,300}?["\']([^"\']{4,160})["\'][\s\S]{0,300}?world\.huanqiu\.com',
            r'([A-Za-z0-9]{8,})[\s\S]{0,120}?article[\s\S]{0,800}?["\']([^"\']{4,160})["\'][\s\S]{0,400}?world\.huanqiu\.com',
        ]  # 覆盖常见 JSON 和压缩脚本格式
        items = []
        seen = set()
        for index, pattern in enumerate(patterns):
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                if index == 1:
                    title, article_id = match
                else:
                    article_id, title = match
                url = f"https://world.huanqiu.com/article/{article_id}"
                if not article_id or article_id in seen or not _is_valid_article_url(url, config):
                    continue
                seen.add(article_id)
                items.append({
                    "url": url,
                    "title": self._clean_title(title),
                })
            if items:
                return items
        return items

    async def _extract_items_from_js_variable(self, page, config: dict) -> list[dict]:  # 从浏览器 JS 变量和自定义元素属性提取文章
        try:
            return await page.evaluate(
                """
                ({config, baseUrl}) => {
                    const results = [];
                    const seen = new Set();
                    const articleIdRegex = config.article_id_regex ? new RegExp(config.article_id_regex) : null;
                    const allowedPrefixes = config.allowed_article_url_prefixes || [];
                    const isValidArticleUrl = (url) => {
                        if (!url) return false;
                        if (allowedPrefixes.length && !allowedPrefixes.some((prefix) => url.startsWith(prefix))) return false;
                        if (!articleIdRegex) return true;
                        const path = url.split('?')[0].replace(/\\/$/, '');
                        const articleId = path.split('/').pop();
                        return articleIdRegex.test(articleId);
                    };
                    const push = (url, title) => {
                        if (!isValidArticleUrl(url) || seen.has(url)) return;
                        seen.add(url);
                        results.push({url, title: (title || url || '').toString().replace(/\\s+/g, ' ').trim()});
                    };
                    const normalizeUrl = (value) => {
                        if (!value) return '';
                        const text = value.toString().replace(/\\\\\\//g, '/');
                        if (/^https?:\\/\\//.test(text)) return text;
                        if (/^\\/article\\//.test(text)) return new URL(text, baseUrl).href;
                        if (/^[A-Za-z0-9]{5,}$/.test(text)) return 'https://world.huanqiu.com/article/' + text;
                        return '';
                    };
                    const readObject = (obj, depth = 0) => {
                        if (!obj || depth > 4) return;
                        if (Array.isArray(obj)) {
                            obj.forEach((item) => readObject(item, depth + 1));
                            return;
                        }
                        if (typeof obj !== 'object') return;
                        const url = normalizeUrl(obj.url || obj.href || obj.link || obj.dataUrl || obj.articleUrl || obj.article_url || obj.articleId || obj.ARTICLE_ID || obj.aid || obj.id);
                        const title = obj.title || obj.name || obj.text || obj.summaryTitle || obj.articleTitle || obj.TITLE;
                        if (url) push(url, title);
                        Object.keys(obj).slice(0, 80).forEach((key) => readObject(obj[key], depth + 1));
                    };
                    Object.keys(window).forEach((key) => {
                        try {
                            if (/(__|data|list|article|news|state|initial|props)/i.test(key)) readObject(window[key], 0);
                        } catch (e) {}
                    });
                    document.querySelectorAll('[data-url], [data-href], [data-article-id], [article-id], [data-id]').forEach((node) => {
                        const raw = node.getAttribute('data-url') || node.getAttribute('data-href') || node.getAttribute('data-article-id') || node.getAttribute('article-id') || node.getAttribute('data-id');
                        push(normalizeUrl(raw), node.innerText || node.textContent || '');
                    });
                    document.querySelectorAll('[class*="item"] a, [class*="list"] a, [class*="card"] a').forEach((node) => {
                        push(normalizeUrl(node.getAttribute('href')), node.innerText || node.textContent || '');
                    });
                    return results;
                }
                """,
                {"config": config, "baseUrl": self.source.url},
            )  # 兼容环球网自定义组件、window 初始化数据和 data-* 属性
        except Exception as e:
            logger.debug(f"JS variable extraction failed: {e}")
            return []

    def _clean_title(self, title: str) -> str:  # 清洗从脚本文本中提取到的标题
        return re.sub(r"\s+", " ", title or "").strip()

    async def _scroll_page(self, page, config: dict) -> None:  # 对无限滚动页面执行滚动加载
        if not config.get("scroll_enabled"):
            return
        scroll_times = int(config.get("scroll_times", 6))
        pause_ms = int(config.get("scroll_pause_ms", 1000))
        last_height = 0
        stable_rounds = 0
        for _ in range(scroll_times):
            height = await page.evaluate("document.body.scrollHeight")  # 获取当前页面高度
            await page.mouse.wheel(0, int(config.get("scroll_distance", 3200)))  # 模拟鼠标滚轮，比直接 evaluate 更像用户行为
            await page.wait_for_timeout(pause_ms + random.randint(0, 350))  # 等待异步加载完成
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height == height:
                stable_rounds += 1
                if stable_rounds >= int(config.get("scroll_stable_rounds", 2)):
                    break  # 连续多次高度不变，认为没有更多内容
            else:
                stable_rounds = 0
            last_height = new_height

    async def _extract_text_by_xpath(self, page, xpath: str | None) -> str | None:  # 用 Playwright 根据 XPath 提取文本
        if not xpath:
            return None
        try:
            locator = page.locator(f"xpath={xpath}").first
            if await locator.count() == 0:
                return await self._extract_text_by_xpath_dom_scan(page, xpath)
            return (await locator.inner_text()).strip()  # Playwright 可处理浏览器实际渲染后的 DOM
        except Exception as e:
            logger.debug(f"Playwright xpath text extraction failed: {e}")
            return await self._extract_text_by_xpath_dom_scan(page, xpath)

    async def _extract_text_by_selector(self, page, selector: str | None) -> str | None:  # 用 CSS 选择器提取文本
        if not selector:
            return None
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                return await self._extract_text_by_selector_dom_scan(page, selector)
            return (await locator.inner_text()).strip()
        except Exception as e:
            logger.debug(f"Playwright selector text extraction failed: {e}")
            return await self._extract_text_by_selector_dom_scan(page, selector)

    async def _extract_text_from_page(self, page, raw_html: str, xpath: str | None, selector: str | None) -> str | None:  # 从页面提取指定文本
        text = await self._extract_text_by_selector(page, selector)
        if not text:
            text = await self._extract_text_by_xpath(page, xpath)
        if text:
            return self._clean_title(text)
        if raw_html and xpath:
            try:
                from lxml import html
                tree = html.fromstring(raw_html)
                nodes = tree.xpath(xpath)
                if nodes:
                    node = nodes[0]
                    value = node.text_content() if hasattr(node, "text_content") else str(node)
                    return self._clean_title(value)
            except Exception as e:
                logger.debug(f"lxml text extraction failed: {e}")
        return None

    async def _extract_text_by_selector_dom_scan(self, page, selector: str | None) -> str | None:  # JS 递归扫描 CSS 文本
        if not selector:
            return None
        try:
            return await page.evaluate(
                """
                (selector) => {
                    const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const find = (root) => {
                        if (!root || !root.querySelector) return null;
                        const node = root.querySelector(selector);
                        if (node) return clean(node.innerText || node.textContent || '');
                        const all = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                        for (const item of all) {
                            if (item.shadowRoot) {
                                const value = find(item.shadowRoot);
                                if (value) return value;
                            }
                        }
                        return null;
                    };
                    return find(document);
                }
                """,
                selector,
            )
        except Exception as e:
            logger.debug(f"DOM selector text scan failed: {e}")
            return None

    async def _extract_text_by_xpath_dom_scan(self, page, xpath: str | None) -> str | None:  # JS 递归扫描 XPath 文本
        if not xpath:
            return None
        try:
            return await page.evaluate(
                """
                (xpath) => {
                    const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const evalXPath = (root) => {
                        try {
                            const doc = root && root.ownerDocument ? root.ownerDocument : document;
                            const result = doc.evaluate(xpath, root || document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                            const node = result.singleNodeValue;
                            if (node) return clean(node.innerText || node.textContent || '');
                        } catch (e) {}
                        return null;
                    };
                    const walk = (root) => {
                        const value = evalXPath(root);
                        if (value) return value;
                        if (!root || !root.querySelectorAll) return null;
                        const all = Array.from(root.querySelectorAll('*'));
                        for (const item of all) {
                            if (item.shadowRoot) {
                                const childValue = walk(item.shadowRoot);
                                if (childValue) return childValue;
                            }
                        }
                        return null;
                    };
                    return walk(document);
                }
                """,
                xpath,
            )
        except Exception as e:
            logger.debug(f"DOM xpath text scan failed: {e}")
            return None

    async def _extract_datetime_from_page(self, page, raw_html: str, xpath: str | None, selector: str | None, parser: str | None):  # 从详情页提取并解析日期
        date_text = await self._extract_text_from_page(page, raw_html, xpath, selector)
        if not date_text:
            date_text = await self._extract_date_text_by_dom_scan(page)  # 通用兜底：扫描页面中的 .date 元素
        if date_text:
            parsed = _parse_article_datetime(date_text, parser)
            if parsed:
                return parsed
        return _extract_article_datetime(raw_html, xpath, parser)  # Playwright 失败时回退到 lxml

    async def _extract_content_html_from_page(self, page, raw_html: str, xpath: str | None, section_xpath: str | None, selector: str | None, base_url: str) -> str | None:  # 从详情页提取正文 HTML
        section_html = await self._extract_article_section_html(page, raw_html, section_xpath)
        if section_html:
            return f'<html><head><base href="{base_url}"></head><body><div class="content"><article>{section_html}</article></div></body></html>'
        content_html = await self._extract_html_by_selector(page, selector)
        if not content_html:
            content_html = await self._extract_html_by_xpath(page, xpath)
        if not content_html:
            content_html = self._extract_content_html_by_lxml(raw_html, xpath)
        if not content_html:
            return None
        return f'<html><head><base href="{base_url}"></head><body><article>{content_html}</article></body></html>'

    async def _wait_for_article_section(self, page, section_xpath: str | None, timeout_ms: int = 15000) -> bool:  # 等待正文 section 出现
        # 先用 Playwright 的 CSS 定位等待正文 section，兼容开放 Shadow DOM 的常见渲染方式。
        for selector in (
            'section[data-type="rtext"]',
            'article section[data-type="rtext"]',
            'article-content-template section[data-type="rtext"]',
        ):
            try:
                await page.locator(selector).first.wait_for(state="attached", timeout=timeout_ms)
                return True
            except Exception:
                continue

        # CSS 没命中时，再退回浏览器侧递归扫描和 XPath 判断。
        try:
            found = await page.evaluate(
                """
                ({ xpath }) => {
                    const findInRoot = (root) => {
                        if (!root) return false;
                        if (root.querySelector && root.querySelector('section[data-type="rtext"]')) {
                            return true;
                        }
                        const all = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                        for (const item of all) {
                            if (item.shadowRoot && findInRoot(item.shadowRoot)) {
                                return true;
                            }
                        }
                        return false;
                    };
                    if (findInRoot(document)) {
                        return true;
                    }
                    if (!xpath) {
                        return false;
                    }
                    try {
                        const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        return !!result.singleNodeValue;
                    } catch (e) {
                        return false;
                    }
                }
                """,
                {"xpath": section_xpath},
            )
            return bool(found)
        except Exception as e:
            logger.debug(f"Check article section readiness failed: {e}")
            return False

    async def _extract_article_section_html(self, page, raw_html: str, section_xpath: str | None) -> str | None:  # 按指定 XPath 提取正文 section 节点
        for selector in (
            'section[data-type="rtext"]',
            'article section[data-type="rtext"]',
            'article-content-template section[data-type="rtext"]',
        ):
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                inner_html = (await locator.inner_html()).strip()
                if inner_html:
                    return f'<section data-type="rtext">{inner_html}</section>'
            except Exception as e:
                logger.debug(f"Extract article section by selector failed for {selector}: {e}")

        dom_section_html = await self._extract_article_section_html_from_dom(page)
        if dom_section_html:
            return dom_section_html

        if not section_xpath:
            return None
        try:
            locator = page.locator(f"xpath={section_xpath}").first
            if await locator.count() > 0:
                inner_html = (await locator.inner_html()).strip()
                if inner_html:
                    return f'<section data-type="rtext">{inner_html}</section>'
        except Exception as e:
            logger.debug(f"Extract article section by xpath failed: {e}")

        try:
            nodes = html.fromstring(raw_html).xpath(section_xpath) if raw_html else []
            if not nodes:
                return None
            return html.tostring(nodes[0], encoding="unicode").strip() or None
        except Exception as e:
            logger.debug(f"lxml article section extraction failed: {e}")
            return None

    async def _extract_article_section_html_from_dom(self, page) -> str | None:  # 递归扫描 DOM 和 Shadow DOM，提取正文段落
        try:
            section_html = await page.evaluate(
                """
                () => {
                    const cleanupSection = (section) => {
                        const clone = section.cloneNode(true);
                        clone.querySelectorAll('script,style,noscript,adv-loader,iframe').forEach((node) => node.remove());
                        const paragraphs = Array.from(clone.querySelectorAll('p'))
                            .map((p) => `<p>${(p.textContent || '').trim()}</p>`)
                            .filter((text) => text !== '<p></p>');
                        if (paragraphs.length > 0) {
                            return `<section data-type="rtext">${paragraphs.join('')}</section>`;
                        }
                        const text = (clone.textContent || '').trim();
                        return text ? `<section data-type="rtext"><p>${text}</p></section>` : '';
                    };
                    const findInRoot = (root) => {
                        if (!root) return '';
                        if (root.querySelector) {
                            const direct = root.querySelector('section[data-type="rtext"]');
                            if (direct) {
                                return cleanupSection(direct);
                            }
                        }
                        const all = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                        for (const item of all) {
                            if (item.shadowRoot) {
                                const value = findInRoot(item.shadowRoot);
                                if (value) {
                                    return value;
                                }
                            }
                        }
                        return '';
                    };
                    return findInRoot(document);
                }
                """
            )
            return section_html.strip() if section_html else None
        except Exception as e:
            logger.debug(f"Extract article section from DOM failed: {e}")
            return None

    async def _extract_html_by_selector(self, page, selector: str | None) -> str | None:  # 用 CSS 选择器提取节点 HTML
        if not selector:
            return None
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                return await self._extract_html_by_selector_dom_scan(page, selector)
            return (await locator.inner_html()).strip()
        except Exception as e:
            logger.debug(f"Playwright selector html extraction failed: {e}")
            return await self._extract_html_by_selector_dom_scan(page, selector)

    async def _extract_html_by_xpath(self, page, xpath: str | None) -> str | None:  # 用 XPath 提取节点 HTML
        if not xpath:
            return None
        try:
            locator = page.locator(f"xpath={xpath}").first
            if await locator.count() == 0:
                return await self._extract_html_by_xpath_dom_scan(page, xpath)
            return (await locator.inner_html()).strip()
        except Exception as e:
            logger.debug(f"Playwright xpath html extraction failed: {e}")
            return await self._extract_html_by_xpath_dom_scan(page, xpath)

    async def _extract_html_by_selector_dom_scan(self, page, selector: str | None) -> str | None:  # JS 递归扫描 CSS 节点 HTML
        if not selector:
            return None
        try:
            return await page.evaluate(
                """
                (selector) => {
                    const find = (root) => {
                        if (!root || !root.querySelector) return null;
                        const node = root.querySelector(selector);
                        if (node) return node.innerHTML || '';
                        const all = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                        for (const item of all) {
                            if (item.shadowRoot) {
                                const value = find(item.shadowRoot);
                                if (value) return value;
                            }
                        }
                        return null;
                    };
                    return find(document);
                }
                """,
                selector,
            )
        except Exception as e:
            logger.debug(f"DOM selector html scan failed: {e}")
            return None

    async def _extract_html_by_xpath_dom_scan(self, page, xpath: str | None) -> str | None:  # JS 递归扫描 XPath 节点 HTML
        if not xpath:
            return None
        try:
            return await page.evaluate(
                """
                (xpath) => {
                    const evalXPath = (root) => {
                        try {
                            const doc = root && root.ownerDocument ? root.ownerDocument : document;
                            const result = doc.evaluate(xpath, root || document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                            const node = result.singleNodeValue;
                            if (node) return node.innerHTML || '';
                        } catch (e) {}
                        return null;
                    };
                    const walk = (root) => {
                        const value = evalXPath(root);
                        if (value) return value;
                        if (!root || !root.querySelectorAll) return null;
                        const all = Array.from(root.querySelectorAll('*'));
                        for (const item of all) {
                            if (item.shadowRoot) {
                                const childValue = walk(item.shadowRoot);
                                if (childValue) return childValue;
                            }
                        }
                        return null;
                    };
                    return walk(document);
                }
                """,
                xpath,
            )
        except Exception as e:
            logger.debug(f"DOM xpath html scan failed: {e}")
            return None

    def _extract_content_html_by_lxml(self, raw_html: str, xpath: str | None) -> str | None:  # lxml 兜底提取正文 HTML
        if not raw_html or not xpath:
            return None
        try:
            from lxml import html
            tree = html.fromstring(raw_html)
            nodes = tree.xpath(xpath)
            if not nodes:
                return None
            node = nodes[0]
            if not hasattr(node, "iterchildren"):
                return str(node).strip()
            parts = [html.tostring(child, encoding="unicode") for child in node.iterchildren()]
            content = "".join(parts).strip() or node.text_content().strip()
            return content
        except Exception as e:
            logger.debug(f"lxml content html extraction failed: {e}")
            return None

    async def _extract_image_from_page(self, page, raw_html: str, xpath: str | None, selector: str | None, base_url: str) -> str | None:  # 从详情页提取图片
        image_url = await self._extract_image_by_selector(page, selector, base_url)
        if not image_url:
            image_url = await self._extract_image_by_xpath(page, xpath, base_url)
        if not image_url:
            image_url = await self._extract_image_by_dom_scan(page, base_url)  # 通用兜底：扫描正文图片
        return image_url or _extract_article_image_url(raw_html, xpath, base_url)  # Playwright 失败时回退到 lxml

    async def _extract_image_by_selector(self, page, selector: str | None, base_url: str) -> str | None:  # 用 CSS 选择器提取图片
        if not selector:
            return None
        try:
            container = page.locator(selector).first
            if await container.count() == 0:
                return None
            img = container.locator("img").first
            if await img.count() == 0:
                return None
            src = await self._first_image_attr(img)
            return urljoin(base_url, src) if src else None
        except Exception as e:
            logger.debug(f"Playwright selector image extraction failed: {e}")
            return None

    async def _extract_image_by_xpath(self, page, xpath: str | None, base_url: str) -> str | None:  # 用 XPath 提取图片
        if not xpath:
            return None
        try:
            container = page.locator(f"xpath={xpath}").first
            if await container.count() == 0:
                return None
            img = container.locator("img").first
            if await img.count() == 0:
                return None
            src = await self._first_image_attr(img)
            return urljoin(base_url, src) if src else None
        except Exception as e:
            logger.debug(f"Playwright xpath image extraction failed: {e}")
            return None

    async def _first_image_attr(self, img) -> str | None:  # 按常见懒加载字段读取图片地址
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            value = await img.get_attribute(attr)
            if value and value.strip() and not value.strip().startswith("data:"):
                return value.strip()
        return None

    async def _extract_date_text_by_dom_scan(self, page) -> str | None:  # 从浏览器 DOM 扫描日期文本，适配部分自定义组件页面
        try:
            return await page.evaluate("""
                () => {
                    const candidates = Array.from(document.querySelectorAll('.date, [class*="date"], time'));
                    for (const node of candidates) {
                        const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (/\\d{4}/.test(text) && /\\d{1,2}[:/]\\d{1,2}/.test(text)) return text;
                    }
                    return null;
                }
            """)  # 兼容环球网这类 .date 内部拆 span 的结构
        except Exception as e:
            logger.debug(f"DOM date scan failed: {e}")
            return None

    async def _extract_image_by_dom_scan(self, page, base_url: str) -> str | None:  # 从浏览器 DOM 扫描第一张有效正文图片
        try:
            src = await page.evaluate("""
                () => {
                    const imgs = Array.from(document.querySelectorAll('article img, [class*="content"] img, img'));
                    for (const img of imgs) {
                        const value = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original') || img.getAttribute('data-lazy-src');
                        if (value && !value.startsWith('data:')) return value;
                    }
                    return null;
                }
            """)  # 通用图片兜底，后续动态站点无需单独写代码
            return urljoin(base_url, src) if src else None
        except Exception as e:
            logger.debug(f"DOM image scan failed: {e}")
            return None

