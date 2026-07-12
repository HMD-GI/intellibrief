import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bootstrap import PROJECT_ROOT  # noqa: F401  # 确保测试运行时项目根目录已加入导入路径。
from crawlers.web_static import StaticCrawler


class StaticCrawlerFallbackTestCase(unittest.TestCase):
    """验证静态爬虫在当天无文章时会回退到最近日期。"""

    @patch("crawlers.web_static.get_source_xpath_config")
    @patch("crawlers.web_static.requests.get")
    @patch("crawlers.web_static.date")
    def test_static_crawler_falls_back_to_latest_article_date(self, mock_date, mock_get, mock_xpath_config):
        # 固定“当天”为 2026-07-12，模拟站点没有当天文章。
        mock_date.today.return_value = SimpleNamespace(isoformat=lambda: "2026-07-12")
        mock_xpath_config.return_value = {
            "article_date_xpath": '//div[@class="date"]',
            "article_image_xpath": None,
            "date_parser": None,
        }

        list_html = """
        <html><body>
            <div class="item"><a href="/news/1"><h2>文章一</h2></a></div>
            <div class="item"><a href="/news/2"><h2>文章二</h2></a></div>
        </body></html>
        """
        detail_html_1 = '<html><body><div class="date">2026-07-10 09:00</div></body></html>'
        detail_html_2 = '<html><body><div class="date">2026-07-09 09:00</div></body></html>'

        # 依次返回列表页和两个详情页响应。
        mock_get.side_effect = [
            Mock(status_code=200, text=list_html, raise_for_status=lambda: None),
            Mock(status_code=200, text=detail_html_1),
            Mock(status_code=200, text=detail_html_2),
        ]

        source = SimpleNamespace(
            parser_config={
                "list_selector": ".item",
                "link_selector": "a",
                "title_selector": "h2",
            },
            name="AIbase - AI资讯",
            url="https://example.com/news",
            id=1,
        )

        crawler = StaticCrawler(source)
        articles = crawler.fetch()

        # 预期只保留最近日期 2026-07-10 的文章。
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].article_date, "2026-07-10")
        self.assertEqual(articles[0].title, "文章一")


if __name__ == "__main__":
    unittest.main()
