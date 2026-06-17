import os  # 导入系统操作系统模块，用于处理环境变量等
from pydantic_settings import BaseSettings  # 从 pydantic_settings 导入 BaseSettings，用于配置管理
from typing import List  # 导入 List 类型提示


SOURCE_XPATH_CONFIGS = {  # 源专属 XPath 配置，后续新增来源时按源 URL 增加独立规则
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


def get_source_xpath_config(source_url: str) -> dict:  # 根据来源 URL 获取专属 XPath 配置
    normalized_url = (source_url or "").rstrip("/")  # 去掉尾部斜杠，避免配置匹配失败
    if normalized_url in SOURCE_XPATH_CONFIGS:
        return SOURCE_XPATH_CONFIGS[normalized_url]
    for configured_url, config in SOURCE_XPATH_CONFIGS.items():
        if normalized_url.startswith(configured_url.rstrip("/") + "/"):
            return config  # 支持同一站点子路径复用配置
    return {}

class Settings(BaseSettings):  # 定义 Settings 类，继承自 BaseSettings
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./intellibrief.db"  # 数据库连接 URL，默认使用本地 SQLite
    
    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"  # Redis 连接 URL，用于 Celery 消息队列和去重缓存
    
    # LLM (大语言模型) 配置：按处理步骤命名，避免在代码中写死厂商名
    FIRST_LLM_API_KEYS: str = ""  # 第一步筛选模型 API Key 列表（逗号分隔支持多 Key）
    FIRST_LLM_MODEL: str = "deepseek-v4-pro"  # 第一步筛选模型名称
    FIRST_LLM_BASE_URL: str = "https://api.deepseek.com"  # 第一步筛选模型兼容 OpenAI 接口地址

    SECOND_LLM_API_KEYS: str = ""  # 第二步摘要模型 API Key 列表（逗号分隔支持多 Key）
    SECOND_LLM_MODEL: str = "deepseek-v4-pro"  # 第二步摘要模型名称
    SECOND_LLM_BASE_URL: str = "https://api.deepseek.com"  # 第二步摘要模型兼容 OpenAI 接口地址

    THIRD_LLM_API_KEYS: str = ""  # 第三步分类模型 API Key 列表（逗号分隔支持多 Key）
    THIRD_LLM_MODEL: str = "deepseek-v4-pro"  # 第三步分类模型名称
    THIRD_LLM_BASE_URL: str = "https://api.deepseek.com"  # 第三步分类模型兼容 OpenAI 接口地址
    
    # 默认信息源配置
    DEFAULT_TOPICS: List[str] = ["大模型", "AI应用"]  # 默认关注的主题列表
    
    # 简报推送配置
    EMAIL_SENDER: str = ""  # 发件人邮箱地址
    EMAIL_PASSWORD: str = ""  # 发件人邮箱授权码或密码
    EMAIL_RECEIVERS: str = ""  # 收件人邮箱地址列表（逗号分隔）
    EMAIL_SMTP_HOST: str = "smtp.qq.com"  # SMTP 服务器地址，可被前端绑定配置覆盖
    EMAIL_SMTP_PORT: int = 465  # SMTP 服务器端口，可被前端绑定配置覆盖
    EMAIL_SMTP_USE_SSL: bool = True  # 是否使用 SMTP_SSL，可被前端绑定配置覆盖
    FEISHU_WEBHOOK: str = ""  # 飞书机器人的 Webhook URL
    FRONTEND_ORIGINS: str = "http://127.0.0.1:5173,http://localhost:5173"  # 独立前端允许跨域访问的地址

    class Config:  # 配置内部类
        env_file = ".env"  # 指定环境变量从 .env 文件加载
        env_file_encoding = "utf-8"  # 指定 .env 文件的编码为 utf-8
        extra = "ignore"  # 忽略 .env 中已废弃的旧配置字段，避免启动报错

    @property  # 将方法转换为属性调用
    def first_llm_keys_list(self) -> List[str]:  # 获取第一步 LLM 的 Key 列表
        return [k.strip() for k in self.FIRST_LLM_API_KEYS.split(",") if k.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def second_llm_keys_list(self) -> List[str]:  # 获取第二步 LLM 的 Key 列表
        return [k.strip() for k in self.SECOND_LLM_API_KEYS.split(",") if k.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def third_llm_keys_list(self) -> List[str]:  # 获取第三步 LLM 的 Key 列表
        return [k.strip() for k in self.THIRD_LLM_API_KEYS.split(",") if k.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def email_receivers_list(self) -> List[str]:  # 获取收件人邮箱列表的方法
        return [r.strip() for r in self.EMAIL_RECEIVERS.split(",") if r.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def frontend_origins_list(self) -> List[str]:  # 获取前端跨域白名单
        return [origin.strip() for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]  # 按逗号分割并过滤空值

settings = Settings()  # 实例化 Settings 对象，供全局使用
