import asyncio
import logging
from threading import RLock

from openai import AsyncOpenAI, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

ALL_LLM_KEYS_FAILED_MESSAGE = "大模型都出现问题，请稍后再试"


class AllLLMKeysFailedError(RuntimeError):
    """所有 LLM Key 都不可用时抛出的统一异常。"""


class LLMRouter:
    """大模型路由器。

    技术选择：
    1. 使用 AsyncOpenAI 实现异步 IO，适合批量 LLM 调用。
    2. 保留按用途分组的模型配置，便于筛选、摘要、分类使用不同模型。
    3. 使用轮询 Key + 指数退避，提升高并发下的稳定性。
    """

    def __init__(self):
        self._key_indexes = {"first": 0, "second": 0, "third": 0}
        self._response_stats: dict[str, dict[str, int]] = {}
        self._lock = RLock()

    def _provider_keys(self, provider: str) -> list[str]:
        # 统一从 Settings 的槽位配置入口读取，避免路由器直接耦合具体字段名。
        keys = settings.get_llm_provider_config(provider)["api_keys"]
        if not keys:
            raise ValueError(f"No {provider} LLM API keys configured.")
        return keys

    def _provider_model(self, provider: str) -> str:
        return settings.get_llm_provider_config(provider)["model"]

    def _provider_base_url(self, provider: str) -> str:
        return settings.get_llm_provider_config(provider)["base_url"]

    def _current_key(self, provider: str, keys: list[str]) -> str:
        with self._lock:
            index = self._key_indexes.get(provider, 0) % len(keys)
            return keys[index]

    def _advance_key(self, provider: str, keys: list[str], api_key: str) -> None:
        with self._lock:
            index = keys.index(api_key) if api_key in keys else self._key_indexes.get(provider, 0) % len(keys)
            self._key_indexes[provider] = (index + 1) % len(keys)

    def _ordered_keys_from_current(self, provider: str) -> list[str]:
        keys = self._provider_keys(provider)
        with self._lock:
            start = self._key_indexes.get(provider, 0) % len(keys)
        return keys[start:] + keys[:start]

    def _mask_key(self, api_key: str) -> str:
        return f"{(api_key or '')[:4]}...."

    def _record_response(self, model: str, success: bool) -> None:
        with self._lock:
            if model not in self._response_stats:
                self._response_stats[model] = {"success": 0, "failure": 0}
            field = "success" if success else "failure"
            self._response_stats[model][field] += 1

    def reset_response_stats(self) -> None:
        with self._lock:
            self._response_stats = {}

    def log_response_stats(self) -> None:
        with self._lock:
            snapshot = dict(self._response_stats)
        for model, stats in snapshot.items():
            logger.info("%s模型响应成功%s次，响应失败%s次", model, stats["success"], stats["failure"])

    def _build_client(self, provider: str, api_key: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=api_key,
            base_url=self._provider_base_url(provider),
            max_retries=0,
        )

    async def _call_with_key_async(
        self,
        provider: str,
        api_key: str,
        messages: list,
        max_retries: int,
        response_format: dict | None = None,
    ) -> str:
        client = self._build_client(provider, api_key)
        model = self._provider_model(provider)
        last_error = None
        max_attempts = max_retries + 1

        for attempt in range(max_attempts):
            try:
                logger.info("大模型: %s，api_key: %s", model, self._mask_key(api_key))
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                response = await client.chat.completions.create(**kwargs)
                self._advance_key(provider, self._provider_keys(provider), api_key)
                self._record_response(model, True)
                return response.choices[0].message.content or ""
            except RateLimitError as exc:
                last_error = exc
                if attempt < max_retries:
                    backoff = min(3 * (2 ** attempt), 20)
                    logger.warning("429 Rate limited, retrying in %ss (attempt %s/%s)", backoff, attempt + 1, max_attempts)
                    await asyncio.sleep(backoff)
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    backoff = min(3 * (2 ** attempt), 20)
                    logger.warning("大模型调用失败，%ss 后重试 (attempt %s/%s): %s", backoff, attempt + 1, max_attempts, exc)
                    await asyncio.sleep(backoff)

        raise last_error or RuntimeError("大模型响应失败")

    async def call_llm_async(
        self,
        provider: str,
        messages: list,
        max_retries: int = 5,
        response_format: dict | None = None,
    ) -> str:
        model = self._provider_model(provider)
        keys = self._ordered_keys_from_current(provider)
        last_error = None
        for api_key in keys:
            try:
                return await self._call_with_key_async(
                    provider=provider,
                    api_key=api_key,
                    messages=messages,
                    max_retries=max_retries,
                    response_format=response_format,
                )
            except Exception as exc:
                last_error = exc
                logger.error("%s 使用 api_key %s 退避结束后失败，切换下一个 Key", model, self._mask_key(api_key))
        self._record_response(model, False)
        logger.error(ALL_LLM_KEYS_FAILED_MESSAGE)
        raise AllLLMKeysFailedError(ALL_LLM_KEYS_FAILED_MESSAGE) from last_error

    def call_llm(
        self,
        provider: str,
        messages: list,
        max_retries: int = 5,
        response_format: dict | None = None,
    ) -> str:
        """兼容同步调用入口。"""

        return asyncio.run(self.call_llm_async(provider, messages, max_retries=max_retries, response_format=response_format))


llm_router = LLMRouter()
