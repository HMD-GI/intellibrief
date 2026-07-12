from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


# 这里保留“代码级结构化配置”。
# 技术原因：
# 1. XPath / Selector 属于嵌套结构化映射，放到 .env 中可读性和可维护性都很差。
# 2. 这类配置和运行环境无关，更适合作为代码常量维护。
# 3. 运行环境相关的数据库、Redis、LLM、天气、通知配置全部迁移到 .env。
SOURCE_XPATH_CONFIGS = {
    "https://news.aibase.cn/news": {
        "article_date_xpath": "/html/body/div[1]/main/div/div[1]/div/div/div[1]/article/div/div/div/div[2]/div/div[2]/div[1]/span[2]",
        "article_image_xpath": "/html/body/div[1]/main/div/div[1]/div/div/div[1]/article/div/div/div/div[4]",
    },
    "https://world.huanqiu.com": {
        "article_title_xpath": "/html/body/article-container-template//div[1]/div/div[1]/article-head-template//div[2]/h1",
        "article_date_xpath": "/html/body/article-container-template//div[1]/div/div[2]/div[1]/layout-block-template//div/article-content-template//div/div[1]/div[1]",
        "article_image_xpath": "/html/body/article-container-template//div[1]/div/div[2]/div[1]/layout-block-template//div/article-content-template//div/div[2]",
        "article_content_xpath": "/html/body/article-container-template//div[1]/div/div[2]/div[1]/layout-block-template//div/article-content-template//div/div[2]",
        "article_section_xpath": "/html/body/article-container-template//div[1]/div/div[2]/div[1]/layout-block-template//div/article-content-template//div/div[2]/article/section",
        "article_title_selector": "article-head-template h1",
        "article_date_selector": "article-content-template .date, .date",
        "article_content_selector": "article-content-template div div:nth-child(2)",
        "article_image_selector": "article-content-template img",
        "date_parser": "huanqiu",
        "dynamic": {
            "item_xpath": "/html/body/channel-container-template//div/div/div/div[2]/div[2]/div[1]/layout-block-template[2]//div/layout-bd-template//div/sketch-feed-template//div/div[1]",
            "list_selector": "a[href*='/article/']",
            "item_selector": ".feed-item.feed-item-a, .feed-item.feed-item-b",
            "link_selector": "a[href*='/article/']",
            "title_selector": "h4",
            "date_selector": ".tool .time, .time",
            "scroll_enabled": True,
            "scroll_times": 10,
            "scroll_pause_ms": 1500,
            "scroll_stable_rounds": 4,
            "initial_wait_ms": 3000,
            "anti_detection": True,
            "capture_network": True,
            "capture_url_keywords": ["huanqiu", "world"],
            "fetch_scripts_fallback": True,
            "max_script_fetch": 30,
            "allowed_article_url_prefixes": ["https://world.huanqiu.com/article/"],
            "require_list_date": True,
            "article_id_regex": r"(?=.*\d)[A-Za-z0-9]{6,}",
            "skip_detail_section_wait": True,
            "wait_after_detail_ms": 0,
        },
    },
}


def get_source_xpath_config(source_url: str) -> dict:
    """根据来源 URL 获取专属 XPath / Selector 配置。"""

    normalized_url = (source_url or "").rstrip("/")
    if normalized_url in SOURCE_XPATH_CONFIGS:
        return SOURCE_XPATH_CONFIGS[normalized_url]
    for configured_url, config in SOURCE_XPATH_CONFIGS.items():
        if normalized_url.startswith(configured_url.rstrip("/") + "/"):
            return config
    return {}


class Settings(BaseSettings):
    """项目全局配置。

    技术说明：
    1. 这里仅负责读取环境变量，不再硬编码运行时参数。
    2. 这样数据库、Redis、LLM、天气、通知等配置都能通过 .env 切换。
    3. 大模型使用 first / second / third 三个槽位，路由层只认槽位，不关心具体厂商。
    """

    DATABASE_URL: str
    SQLITE_MIGRATION_SOURCE: str
    REDIS_URL: str
    REDIS_FALLBACK_URL: str = ""

    FIRST_LLM_API_KEYS: str
    FIRST_LLM_MODEL: str
    FIRST_LLM_BASE_URL: str

    SECOND_LLM_API_KEYS: str
    SECOND_LLM_MODEL: str
    SECOND_LLM_BASE_URL: str

    THIRD_LLM_API_KEYS: str
    THIRD_LLM_MODEL: str
    THIRD_LLM_BASE_URL: str

    DEFAULT_TOPICS: List[str] = Field(default_factory=list)
    EMAIL_SENDER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_RECEIVERS: str = ""
    EMAIL_SMTP_HOST: str
    EMAIL_SMTP_PORT: int
    EMAIL_SMTP_USE_SSL: bool
    FEISHU_WEBHOOK: str = ""

    WEATHER_PROVIDER: str
    WEATHER_REQUEST_TIMEOUT: int
    QWEATHER_API_KEY: str = ""
    QWEATHER_GEO_BASE_URL: str
    QWEATHER_API_BASE_URL: str
    OPEN_METEO_API_BASE_URL: str
    OPEN_METEO_GEO_BASE_URL: str
    DEFAULT_WEATHER_REGION: str

    FRONTEND_ORIGINS: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_llm_provider_config(self, provider: str) -> dict:
        """按槽位返回统一的 LLM 配置。

        原理：
        1. 将 first / second / third 三组环境变量收敛到一个统一访问入口。
        2. 路由器只依赖这个方法，就不会散落地绑定具体字段名。
        3. 后续只改 .env 中的模型名、URL、Key，即可切换模型供应商。
        """

        provider_name = (provider or "").strip().lower()
        mapping = {
            "first": {
                "api_keys": self.first_llm_keys_list,
                "model": self.FIRST_LLM_MODEL,
                "base_url": self.FIRST_LLM_BASE_URL,
            },
            "second": {
                "api_keys": self.second_llm_keys_list,
                "model": self.SECOND_LLM_MODEL,
                "base_url": self.SECOND_LLM_BASE_URL,
            },
            "third": {
                "api_keys": self.third_llm_keys_list,
                "model": self.THIRD_LLM_MODEL,
                "base_url": self.THIRD_LLM_BASE_URL,
            },
        }
        if provider_name not in mapping:
            raise ValueError(f"Unknown provider: {provider}")
        return mapping[provider_name]

    @property
    def first_llm_keys_list(self) -> List[str]:
        """将第一槽位的多 Key 字符串拆分成列表。"""

        return [key.strip() for key in self.FIRST_LLM_API_KEYS.split(",") if key.strip()]

    @property
    def second_llm_keys_list(self) -> List[str]:
        """将第二槽位的多 Key 字符串拆分成列表。"""

        return [key.strip() for key in self.SECOND_LLM_API_KEYS.split(",") if key.strip()]

    @property
    def third_llm_keys_list(self) -> List[str]:
        """将第三槽位的多 Key 字符串拆分成列表。"""

        return [key.strip() for key in self.THIRD_LLM_API_KEYS.split(",") if key.strip()]

    @property
    def email_receivers_list(self) -> List[str]:
        """将邮件接收人字符串拆分成列表。"""

        return [receiver.strip() for receiver in self.EMAIL_RECEIVERS.split(",") if receiver.strip()]

    @property
    def frontend_origins_list(self) -> List[str]:
        """将前端 CORS 白名单字符串拆分成列表。"""

        return [origin.strip() for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]


settings = Settings()
