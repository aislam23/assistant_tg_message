"""
DeepSeek провайдер (через OpenAI-совместимый клиент).
"""
from typing import List, Union

from loguru import logger
from openai import AsyncOpenAI

from app.config import settings

from .base import BaseAIService


class DeepSeekService(BaseAIService):
    """Обёртка над openai.AsyncOpenAI с base_url DeepSeek."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.deepseek_api_key:
                raise RuntimeError(
                    "DEEPSEEK_API_KEY не задан — DeepSeek-сервис недоступен."
                )
            self._client = AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
        return self._client

    async def generate_response(
        self,
        system_prompt: Union[List[dict], str],
        messages: List[dict],
        model: str,
    ) -> str:
        """
        DeepSeek не знает о блоках/cache_control — схлопываем список в строку.
        """
        if isinstance(system_prompt, list):
            system_text = "\n\n".join(
                block.get("text", "")
                for block in system_prompt
                if block.get("type") == "text"
            )
        else:
            system_text = system_prompt or ""

        payload = []
        if system_text:
            payload.append({"role": "system", "content": system_text})
        payload.extend(messages)

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=payload,
            )
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            raise

        return response.choices[0].message.content or ""
