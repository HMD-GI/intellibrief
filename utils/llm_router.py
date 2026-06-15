import logging  # 导入日志模块
import time  # 导入 time 用于等待
from openai import OpenAI, RateLimitError  # 导入 OpenAI 官方 SDK 客户端和限流异常
from app.config import settings  # 导入配置

logger = logging.getLogger(__name__)  # 初始化日志

ALL_LLM_KEYS_FAILED_MESSAGE = "大模型都出现问题，请稍后再试"  # 所有 API Key 均失败时的统一提示

class AllLLMKeysFailedError(RuntimeError):  # 所有 API Key 完整退避后仍失败的异常
    pass

class LLMRouter:  # 定义 LLM 路由器类
    def __init__(self):  # 初始化方法
        self.filter_llm_keys = settings.filter_llm_keys_list  # 筛选 LLM 的 API Keys
        self.summary_llm_keys = settings.summary_llm_keys_list  # 摘要 LLM 的 API Keys
        self._key_indexes = {"zhipu": 0, "deepseek": 0}  # 按供应商记录当前轮询到的 Key 下标
        self._response_stats = {}  # 记录各模型最终成功和最终失败次数

    def _provider_keys(self, provider: str) -> list[str]:  # 获取供应商对应的 API Key 列表
        if provider == "zhipu":  # 筛选 LLM（当前默认 Zhipu）
            if not self.filter_llm_keys:  # 检查是否配置了 Key
                raise ValueError("No filter LLM API keys configured.")  # 如果没有则抛出异常
            return self.filter_llm_keys
        elif provider == "deepseek":  # 摘要 LLM（当前默认 DeepSeek）
            if not self.summary_llm_keys:  # 检查是否配置了 Key
                raise ValueError("No summary LLM API keys configured.")  # 如果没有则抛出异常
            return self.summary_llm_keys
        raise ValueError(f"Unknown provider: {provider}")  # 提供商未知时抛出异常

    def _provider_model(self, provider: str) -> str:  # 获取供应商对应的模型名
        if provider == "zhipu":  # 筛选 LLM
            return settings.FILTER_LLM_MODEL
        if provider == "deepseek":  # 摘要 LLM
            return settings.SUMMARY_LLM_MODEL
        raise ValueError(f"Unknown provider: {provider}")

    def _provider_base_url(self, provider: str) -> str:  # 获取供应商对应的基础 URL（从 config.py 读取）
        if provider == "zhipu":  # 筛选 LLM
            return settings.FILTER_LLM_BASE_URL
        if provider == "deepseek":  # 摘要 LLM
            return settings.SUMMARY_LLM_BASE_URL
        raise ValueError(f"Unknown provider: {provider}")

    def _get_client(self, provider: str, key: str | None = None) -> tuple[OpenAI, str, str]:  # 获取客户端、模型和当前 Key
        keys = self._provider_keys(provider)
        key = key or self._current_key(provider, keys)  # 未指定 Key 时使用当前轮询 Key
        client = OpenAI(api_key=key, base_url=self._provider_base_url(provider), max_retries=0)  # 禁用 SDK 内置重试，统一使用项目退避逻辑
        model = self._provider_model(provider)
        return client, model, key  # 返回客户端实例、模型名称和当前 Key

    def _current_key(self, provider: str, keys: list[str]) -> str:  # 获取当前轮询 Key
        index = self._key_indexes.get(provider, 0) % len(keys)
        return keys[index]

    def _advance_key(self, provider: str, keys: list[str]) -> None:  # 成功调用后切换到下一个 Key
        index = self._key_indexes.get(provider, 0) % len(keys)
        self._key_indexes[provider] = (index + 1) % len(keys)

    def _set_key_index(self, provider: str, key: str) -> None:  # 将轮询指针设置到指定 Key
        keys = self._provider_keys(provider)
        self._key_indexes[provider] = keys.index(key)

    def _ordered_keys_from_current(self, provider: str) -> list[str]:  # 从当前 Key 开始按轮询顺序返回所有 Key
        keys = self._provider_keys(provider)
        start = self._key_indexes.get(provider, 0) % len(keys)
        return keys[start:] + keys[:start]

    def _mask_key(self, api_key: str) -> str:  # 只展示 API Key 前 4 位
        return f"{(api_key or '')[:4]}...."

    def _record_response(self, model: str, success: bool) -> None:  # 记录模型最终响应结果
        if model not in self._response_stats:
            self._response_stats[model] = {"success": 0, "failure": 0}
        field = "success" if success else "failure"
        self._response_stats[model][field] += 1

    def log_response_stats(self) -> None:  # 输出大模型最终响应统计
        for model, stats in self._response_stats.items():
            logger.info(f"{model}模型响应成功{stats['success']}次，响应失败{stats['failure']}次")

    def reset_response_stats(self) -> None:  # 清空本轮运行的大模型响应统计
        self._response_stats = {}

    def _call_with_key(self, provider: str, api_key: str, messages: list, max_retries: int, response_format: dict = None) -> str:  # 使用单个 Key 完成完整退避流程
        client, model, api_key = self._get_client(provider, api_key)  # 固定当前 Key，失败期间不切换 Key
        last_error = None
        max_attempts = max_retries + 1  # 初始调用 + 5 次退避重试（共 6 次尝试机会）
        for attempt in range(max_attempts):
            try:
                logger.info(f"大模型: {model}，api_key: {self._mask_key(api_key)}")  # 每次请求前记录模型和 Key 前 4 位
                kwargs = {  # 构建调用参数字典
                    "model": model,  # 指定模型
                    "messages": messages,  # 传入对话上下文
                    "temperature": 0.3,  # 设置较低的温度，保证输出的稳定性
                }
                if response_format:  # 如果指定了返回格式（如 JSON）
                    kwargs["response_format"] = response_format  # 加入到参数中

                response = client.chat.completions.create(**kwargs)  # 发起 API 调用
                self._advance_key(provider, self._provider_keys(provider))  # 成功返回后切换到下一个 Key
                self._record_response(model, True)  # 记录最终成功响应
                return response.choices[0].message.content  # 返回模型回复的内容文本

            except RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    backoff = min(3 * (2 ** attempt), 20)  # 指数退避从 3 秒开始，最高 20 秒
                    logger.warning(f"⚠️ 429 限流（第{attempt + 1}次重试/{max_retries}次），等待 {backoff}s 后重试...")
                    time.sleep(backoff)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    backoff = min(3 * (2 ** attempt), 20)  # 普通异常也按同一退避策略重试
                    logger.warning(f"⚠️ 大模型调用失败（第{attempt + 1}次重试/{max_retries}次），等待 {backoff}s 后重试: {e}")
                    time.sleep(backoff)

        # 5 次退避重试全部失败
        raise last_error or RuntimeError("大模型响应失败")  # 抛出最后一次异常，交由上层按原逻辑处理

    def call_llm(self, provider: str, messages: list, max_retries: int = 5, response_format: dict = None) -> str:  # 调用大模型的核心方法
        model = self._provider_model(provider)
        keys = self._ordered_keys_from_current(provider)  # 从当前 Key 开始依次尝试全部 Key
        last_error = None

        for api_key in keys:
            self._set_key_index(provider, api_key)  # 当前 Key 失败期间保持不切换
            try:
                return self._call_with_key(provider, api_key, messages, max_retries, response_format)
            except Exception as e:
                last_error = e
                logger.error(f"❌ {model} 使用 api_key {self._mask_key(api_key)} 退避 {max_retries} 次后仍失败，切换下一个 Key")

        self._record_response(model, False)  # 所有 Key 都失败时，记为一次最终失败响应
        logger.error(ALL_LLM_KEYS_FAILED_MESSAGE)
        raise AllLLMKeysFailedError(ALL_LLM_KEYS_FAILED_MESSAGE) from last_error

llm_router = LLMRouter()  # 实例化一个全局的路由对象
