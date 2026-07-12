import logging
import re
from datetime import date, datetime
from typing import List
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from app.config import get_source_xpath_config
from crawlers.base import BaseCrawler, RawArticle

logger = logging.getLogger(__name__)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _parse_chinese_article_datetime(date_text: str) -> datetime | None:
    """解析中文日期格式，例如“2026年6月11日 15:01”或相近格式。"""

    numbers = re.findall(r"\d+", date_text or "")
    if len(numbers) < 5:
        return None
    year, month, day, hour, minute = map(int, numbers[:5])
    return datetime(year, month, day, hour, minute)


def _parse_huanqiu_article_datetime(date_text: str) -> datetime | None:
    """解析环球网详情页日期格式，例如“-2026- 06/16 13:58”。"""

    normalized = re.sub(r"\s+", " ", date_text or "").strip()
    match = re.search(r"-?\s*(\d{4})\s*-?\s+(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{1,2})", normalized)
    if not match:
        return None
    year, month, day, hour, minute = map(int, match.groups())
    return datetime(year, month, day, hour, minute)


def _parse_iso_article_datetime(date_text: str) -> datetime | None:
    """解析标准日期格式，例如“2026-06-16 16:59”。"""

    normalized = re.sub(r"\s+", " ", date_text or "").strip()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", normalized)
    if not match:
        return None
    year, month, day, hour, minute = map(int, match.groups())
    return datetime(year, month, day, hour, minute)


def _parse_unix_article_datetime(date_text: str) -> datetime | None:
    """解析秒级或毫秒级 Unix 时间戳。"""

    normalized = str(date_text or "").strip()
    if not re.fullmatch(r"\d{10,16}", normalized):
        return None
    try:
        timestamp = int(normalized)
        seconds = timestamp / 1000 if timestamp >= 10**12 else timestamp
        return datetime.fromtimestamp(seconds, tz=SHANGHAI_TZ).replace(tzinfo=None)
    except Exception:
        return None


def _parse_article_datetime(date_text: str, parser: str | None = None) -> datetime | None:
    """根据来源配置选择日期解析顺序。"""

    if parser == "huanqiu":
        parsers = [
            _parse_unix_article_datetime,
            _parse_huanqiu_article_datetime,
            _parse_iso_article_datetime,
            _parse_chinese_article_datetime,
        ]
    else:
        parsers = [
            _parse_unix_article_datetime,
            _parse_chinese_article_datetime,
            _parse_iso_article_datetime,
            _parse_huanqiu_article_datetime,
        ]
    for parse_func in parsers:
        parsed = parse_func(date_text)
        if parsed:
            return parsed
    return None


def _extract_article_datetime(raw_html: str, date_xpath: str | None, date_parser: str | None = None) -> datetime | None:
    """按 XPath 从详情页提取发布日期。"""

    if not raw_html or not date_xpath:
        return None
    try:
        from lxml import html

        tree = html.fromstring(raw_html)
        nodes = tree.xpath(date_xpath)
        if not nodes:
            return None
        node = nodes[0]
        date_text = node.text_content().strip() if hasattr(node, "text_content") else str(node).strip()
        return _parse_article_datetime(date_text, date_parser)
    except Exception as exc:
        logger.warning("Failed to extract article date by XPath: %s", exc)
        return None


def _extract_article_image_url(raw_html: str, image_xpath: str | None, base_url: str) -> str | None:
    """按 XPath 从详情页提取首张文章配图。"""

    if not raw_html or not image_xpath:
        return None
    try:
        from lxml import html

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
        )
        if not src:
            return None
        src = src.strip()
        if not src or src.startswith("data:"):
            return None
        return urljoin(base_url, src)
    except Exception as exc:
        logger.warning("Failed to extract article image by XPath: %s", exc)
        return None


class StaticCrawler(BaseCrawler):
    """静态网页爬虫。

    技术方案：
    1. 先完整抓取列表中所有可解析日期的文章候选。
    2. 若存在当天文章，则只返回当天文章。
    3. 若当天没有文章，则自动回退到“最近有文章的日期”，并只返回该日期的文章。

    这样做的原因：
    1. AI 资讯站点更新不稳定，严格只取当天会经常返回 0 篇。
    2. 统一在爬虫层做日期回退，比把旧文章混到后续流程里更可控。
    3. 后续调度层可以直接读取本次爬虫返回的目标日期，不必再猜测。
    """

    def fetch(self) -> List[RawArticle]:
        results: list[RawArticle] = []
        try:
            config = self.source.parser_config or {}
            list_selector = config.get("list_selector")
            link_selector = config.get("link_selector", "a")
            title_selector = config.get("title_selector")
            xpath_config = get_source_xpath_config(self.source.url)
            article_date_xpath = xpath_config.get("article_date_xpath")
            article_image_xpath = xpath_config.get("article_image_xpath")
            date_parser = xpath_config.get("date_parser")

            if not list_selector:
                logger.error("No list_selector for source %s", self.source.name)
                return results

            response = requests.get(self.source.url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select(list_selector)

            article_candidates: list[RawArticle] = []
            today_str = date.today().isoformat()

            for item in items:
                link_tag = item.select_one(link_selector) if item.name != "a" else item
                if not link_tag or not link_tag.get("href"):
                    continue

                url = urljoin(self.source.url, link_tag["href"])
                title_node = item.select_one(title_selector) if title_selector else None
                title = title_node.get_text(strip=True) if title_node else link_tag.get_text(strip=True)

                try:
                    detail_response = requests.get(url, timeout=10)
                    raw_html = detail_response.text if detail_response.status_code == 200 else ""
                except Exception as exc:
                    logger.error("Failed to fetch details for %s: %s", url, exc)
                    raw_html = ""

                if not raw_html:
                    continue

                published_at = _extract_article_datetime(raw_html, article_date_xpath, date_parser)
                if not published_at:
                    logger.info("Skip article without parsable date: %s", url)
                    continue

                article_date = published_at.date().isoformat()
                image_url = _extract_article_image_url(raw_html, article_image_xpath, url)
                article_candidates.append(
                    RawArticle(
                        url=url,
                        title=title,
                        raw_html=raw_html,
                        published_date=published_at,
                        source_id=self.source.id,
                        article_date=article_date,
                        image_url=image_url,
                    )
                )

            if not article_candidates:
                return results

            available_dates = sorted({item.article_date for item in article_candidates if item.article_date}, reverse=True)
            if not available_dates:
                return results

            target_date = today_str if today_str in available_dates else available_dates[0]
            if target_date != today_str:
                logger.info(
                    "No today articles found for %s, fallback to latest article date: %s",
                    self.source.name,
                    target_date,
                )

            for article in article_candidates:
                if article.article_date == target_date:
                    results.append(article)
                else:
                    logger.info("Skip article outside selected date %s: %s", target_date, article.url)
        except Exception as exc:
            logger.error("Error crawling static page %s: %s", self.source.url, exc)

        return results
