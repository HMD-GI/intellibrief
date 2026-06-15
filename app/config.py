import os  # 导入系统操作系统模块，用于处理环境变量等
from pydantic_settings import BaseSettings  # 从 pydantic_settings 导入 BaseSettings，用于配置管理
from typing import List  # 导入 List 类型提示


SOURCE_XPATH_CONFIGS = {  # 源专属 XPath 配置，后续新增来源时按源 URL 增加独立规则
    "https://news.aibase.cn/news": {
        "article_date_xpath": "/html/body/div[1]/main/div/div[1]/div/div/div[1]/article/div/div/div/div[2]/div/div[2]/div[1]/span[2]",
        "article_image_xpath": "/html/body/div[1]/main/div/div[1]/div/div/div[1]/article/div/div/div/div[4]",
    }
}


def get_source_xpath_config(source_url: str) -> dict:  # 根据来源 URL 获取专属 XPath 配置
    normalized_url = (source_url or "").rstrip("/")  # 去掉尾部斜杠，避免配置匹配失败
    return SOURCE_XPATH_CONFIGS.get(normalized_url, {})

class Settings(BaseSettings):  # 定义 Settings 类，继承自 BaseSettings
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./intellibrief.db"  # 数据库连接 URL，默认使用本地 SQLite
    
    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"  # Redis 连接 URL，用于 Celery 消息队列和去重缓存
    
    # LLM (大语言模型) 配置
    # 筛选 LLM（默认智谱 GLM，用于文章筛选+分类）
    FILTER_LLM_API_KEYS: str = ""  # 筛选 LLM 的 API Key 列表（逗号分隔支持多 Key）
    #FILTER_LLM_MODEL: str = "glm-4.7-flash"  # 筛选 LLM 的模型名称
    #FILTER_LLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4/"  # 筛选 LLM 的兼容 OpenAI 接口地址
    FILTER_LLM_MODEL: str = "deepseek-v4-pro"  # 筛选 LLM 的模型名称
    FILTER_LLM_BASE_URL: str = "https://api.deepseek.com"  # 筛选 LLM 的兼容 OpenAI 接口地址

    # 摘要 LLM（默认 DeepSeek，用于生成深度摘要）
    SUMMARY_LLM_API_KEYS: str = ""  # 摘要 LLM 的 API Key 列表（逗号分隔支持多 Key）
    SUMMARY_LLM_MODEL: str = "deepseek-v4-pro"  # 摘要 LLM 的模型名称
    SUMMARY_LLM_BASE_URL: str = "https://api.deepseek.com"  # 摘要 LLM 的兼容 OpenAI 接口地址
    
    # 默认信息源配置
    DEFAULT_TOPICS: List[str] = ["大模型", "AI应用"]  # 默认关注的主题列表
    
    # 简报推送配置
    EMAIL_SENDER: str = ""  # 发件人邮箱地址
    EMAIL_PASSWORD: str = ""  # 发件人邮箱授权码或密码
    EMAIL_RECEIVERS: str = ""  # 收件人邮箱地址列表（逗号分隔）
    FEISHU_WEBHOOK: str = ""  # 飞书机器人的 Webhook URL

    class Config:  # 配置内部类
        env_file = ".env"  # 指定环境变量从 .env 文件加载
        env_file_encoding = "utf-8"  # 指定 .env 文件的编码为 utf-8

    @property  # 将方法转换为属性调用
    def filter_llm_keys_list(self) -> List[str]:  # 获取筛选 LLM 的 Key 列表
        return [k.strip() for k in self.FILTER_LLM_API_KEYS.split(",") if k.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def summary_llm_keys_list(self) -> List[str]:  # 获取摘要 LLM 的 Key 列表
        return [k.strip() for k in self.SUMMARY_LLM_API_KEYS.split(",") if k.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

    @property  # 将方法转换为属性调用
    def email_receivers_list(self) -> List[str]:  # 获取收件人邮箱列表的方法
        return [r.strip() for r in self.EMAIL_RECEIVERS.split(",") if r.strip()]  # 按逗号分割并去除空白字符，过滤空字符串

settings = Settings()  # 实例化 Settings 对象，供全局使用
