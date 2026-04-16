"""
Claude (Anthropic) провайдер.
"""
from typing import List, Union

import anthropic
from loguru import logger

from app.config import settings

from .base import BaseAIService


class ClaudeService(BaseAIService):
    """Обёртка над anthropic.AsyncAnthropic с поддержкой prompt caching."""

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        """Ленивая инициализация клиента."""
        if self._client is None:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY не задан — Claude-сервис недоступен."
                )
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def generate_response(
        self,
        system_prompt: Union[List[dict], str],
        messages: List[dict],
        model: str,
    ) -> str:
        """
        Вызывает Claude и возвращает текст первого блока ответа.
        system_prompt обычно приходит как list[dict] от ContextManager
        (с cache_control на статичных блоках).
        """
        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            )
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise

        # Ответ Claude — список блоков. Берём первый text-блок.
        for block in response.content:
            # SDK возвращает объекты с .type и .text; на всякий случай
            # поддерживаем и dict-форму.
            block_type = getattr(block, "type", None) or block.get("type")  # type: ignore[union-attr]
            if block_type == "text":
                return getattr(block, "text", None) or block.get("text", "")  # type: ignore[union-attr]

        logger.warning("Claude response has no text block")
        return ""
