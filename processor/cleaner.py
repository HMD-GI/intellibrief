import logging
import re
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """压缩多余空白，保留正文段落结构。"""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_rtext_html(raw_html: str) -> str:
    """从原始 HTML 中切出 data-type=rtext 的 section 片段。"""
    section_pattern = re.compile(
        r"<section\b[^>]*data-type=[\"']rtext[\"'][^>]*>.*?</section>",
        re.IGNORECASE | re.DOTALL,
    )
    match = section_pattern.search(raw_html)
    return match.group(0) if match else ""


def _extract_embedded_article_html(raw_html: str) -> str:
    """从被转义或嵌入脚本文本中的 article/section 片段中提取正文 HTML。"""
    candidates = [raw_html]
    try:
        unescaped_once = unescape(raw_html)
        if unescaped_once != raw_html:
            candidates.append(unescaped_once)
        unescaped_twice = unescape(unescaped_once)
        if unescaped_twice not in candidates:
            candidates.append(unescaped_twice)
    except Exception:
        pass

    patterns = [
        re.compile(r"<section\b[^>]*data-type=[\"']rtext[\"'][^>]*>.*?</section>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<article\b[^>]*>\s*<section\b[^>]*data-type=[\"']rtext[\"'][^>]*>.*?</section>\s*</article>", re.IGNORECASE | re.DOTALL),
    ]
    for candidate in candidates:
        for pattern in patterns:
            match = pattern.search(candidate)
            if match:
                return match.group(0)
    return ""


def _extract_text_from_node(node) -> str:
    """清理节点中的广告和脚本，只保留正文文本。"""
    for child in node.find_all(["script", "style", "noscript", "adv-loader", "iframe"]):
        child.decompose()

    paragraphs = node.find_all("p")
    if paragraphs:
        lines = [p.get_text(" ", strip=True) for p in paragraphs]
        return _normalize_text("\n".join(line for line in lines if line))

    return _normalize_text(node.get_text(separator="\n", strip=True))


def extract_clean_content(raw_html: str, url: str = "") -> str:
    """
    提取正文纯文本。
    环球网优先走 article-content-template 组件，其它站点走通用 section/data-type=rtext 逻辑。
    """
    if not raw_html:
        return ""

    try:
        soup = BeautifulSoup(raw_html, "html.parser")

        # 环球网专属：正文实际挂在 article-content-template 组件内部。
        if "world.huanqiu.com" in url:
            content_node = soup.select_one("article-content-template div div:nth-child(2)")
            if content_node is None:
                content_node = soup.select_one("layout-block-template article-content-template div div:nth-child(2)")
            if content_node is not None:
                return _extract_text_from_node(content_node)

            # 环球网兜底：正文可能作为字符串嵌在模板或脚本文本里，需要先反转义再二次解析。
            embedded_html = _extract_embedded_article_html(raw_html)
            if embedded_html:
                embedded_soup = BeautifulSoup(embedded_html, "html.parser")
                embedded_section = embedded_soup.select_one('section[data-type="rtext"]') or embedded_soup.find("section")
                if embedded_section is not None:
                    return _extract_text_from_node(embedded_section)

        content_node = soup.select_one("div.content")
        if content_node is None:
            content_node = soup.find("div", class_="content")

        search_root = content_node or soup
        section_node = search_root.select_one('article section[data-type="rtext"]')
        if section_node is None:
            section_node = search_root.find("section", attrs={"data-type": "rtext"})
        if section_node is None:
            section_node = soup.select_one('section[data-type="rtext"]')

        if section_node is None:
            # 结构不稳定时，从原始 HTML 里切出正文 section 再做纯文本提取。
            section_html = _extract_rtext_html(raw_html)
            if not section_html:
                section_html = _extract_embedded_article_html(raw_html)
            if not section_html:
                logger.warning(f'No <section data-type="rtext"> node found for url {url}')
                return ""
            section_node = BeautifulSoup(section_html, "html.parser")

        return _extract_text_from_node(section_node)
    except Exception as exc:
        logger.error(f"extract_clean_content failed for url {url}: {exc}")
        return ""


def extract_first_image_url(raw_html: str, base_url: str = "") -> str:
    """提取页面中的第一张图片地址。"""
    if not raw_html:
        return ""

    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        img_tag = soup.find("img")
        if not img_tag:
            return ""

        src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-original")
        if not src:
            return ""

        src = src.strip()
        if not src or src.startswith("data:"):
            return ""

        return urljoin(base_url, src) if base_url else src
    except Exception as exc:
        logger.error(f"extract_first_image_url failed: {exc}")
        return ""
