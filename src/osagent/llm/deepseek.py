"""DeepSeek 客户端（兼容 OpenAI 协议）。

设计要点：
- 统一从 settings 读 key / base_url / model；
- 默认 temperature=0，便于复现；
- 带重试（tenacity）；
- 提供 ping() 用于冒烟测试；
- 后续 chat() / chat_json() 由 Agent 直接调用。
"""
from __future__ import annotations

import time
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from ..logging import logger


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        api_key = api_key or settings.deepseek_api_key
        if not api_key or api_key.startswith("sk-xxxx"):
            raise RuntimeError(
                "未配置 DEEPSEEK_API_KEY，请在 .env 中填入有效 key"
            )
        self.model = model or settings.deepseek_model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or settings.deepseek_base_url,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """普通对话，返回纯文本。"""
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            params["response_format"] = response_format
        params.update(kwargs)

        resp = self.client.chat.completions.create(**params)
        return resp.choices[0].message.content or ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def chat_full(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """对话并返回完整结构：{answer, model, usage, latency_ms}。

        QA agent 需要 usage 透传以便前端展示成本与延迟。
        """
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            params["response_format"] = response_format
        params.update(kwargs)

        t0 = time.time()
        resp = self.client.chat.completions.create(**params)
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "answer": resp.choices[0].message.content or "",
            "model": resp.model,
            "usage": resp.usage.model_dump() if resp.usage else {},
            "latency_ms": latency_ms,
        }

    def ping(self) -> dict[str, Any]:
        """冒烟测试：返回模型、用量、回答。"""
        logger.info(f"ping DeepSeek: model={self.model}, base_url={settings.deepseek_base_url}")
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "用一句中文回答：你是谁？现在能正常工作吗？"},
            ],
            temperature=0.0,
            max_tokens=128,
        )
        return {
            "model": resp.model,
            "answer": resp.choices[0].message.content,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }


# 单例
_client: DeepSeekClient | None = None


def get_client() -> DeepSeekClient:
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
