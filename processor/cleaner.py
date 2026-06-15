from readability import Document  # 导入 readability 库，用于提取正文
from bs4 import BeautifulSoup  # 导入 BeautifulSoup，用于解析和清洗 HTML
import re  # 导入正则表达式库
import logging  # 导入日志模块
from urllib.parse import urljoin  # 导入 urljoin，用于将相对图片链接拼接成绝对链接

logger = logging.getLogger(__name__)  # 初始化日志

def extract_clean_content(raw_html: str, url: str = "") -> str:  # 定义提取和清洗正文的函数
    """
    从原始 HTML 中提取主要内容并进行清理。
    """
    if not raw_html:  # 如果传入的 HTML 为空
        return ""  # 返回空字符串
        
    try:  # 开启异常捕获
        doc = Document(raw_html)  # 使用 readability 解析 HTML
        summary_html = doc.summary()  # 提取网页的核心正文（带 HTML 标签）
        
        soup = BeautifulSoup(summary_html, 'html.parser')  # 再次使用 BeautifulSoup 解析正文 HTML
        text = soup.get_text(separator='\n')  # 提取纯文本，使用换行符分隔块级元素
        
        # 清理多余的空白字符
        text = re.sub(r'\n+', '\n', text)  # 将多个连续的换行替换为单个换行
        text = re.sub(r' +', ' ', text)  # 将多个连续的空格替换为单个空格
        
        return text.strip()  # 返回去除首尾空白的纯文本
    except Exception as e:  # 捕获异常
        logger.error(f"Error cleaning content for url {url}: {e}")  # 记录清理失败的日志
        # 降级方案：直接提取所有文本
        try:  # 开启降级异常捕获
            soup = BeautifulSoup(raw_html, 'html.parser')  # 直接解析全网页
            return soup.get_text(separator='\n', strip=True)  # 提取纯文本
        except Exception:  # 如果还是失败
            return ""  # 返回空字符串

def extract_first_image_url(raw_html: str, base_url: str = "") -> str:  # 从原始 HTML 中提取第一张图片的 URL
    """
    提取文章中的第一张图片链接，用于保存到本地作为周报配图。
    """
    if not raw_html:
        return ""

    try:
        soup = BeautifulSoup(raw_html, "html.parser")  # 解析原始 HTML
        img_tag = soup.find("img")  # 查找第一张 img 标签
        if not img_tag:
            return ""

        src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-original")  # 常见图片字段
        if not src:
            return ""

        src = src.strip()
        if not src or src.startswith("data:"):
            return ""

        return urljoin(base_url, src) if base_url else src  # 将相对路径拼接为绝对路径
    except Exception as e:
        logger.error(f"extract_first_image_url failed: {e}")  # 记录错误
        return ""
