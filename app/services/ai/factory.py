"""
Фабрика AI-сервисов по префиксу имени модели.
"""
from loguru import logger

from app.config import settings

from .base import BaseAIService
from .claude_provider import ClaudeService
from .deepseek_provider import DeepSeekService


_claude: ClaudeService | None = None
_deepseek: DeepSeekService | None = None


def _get_claude() -> ClaudeService:
    global _claude
    if _claude is None:
        _claude = ClaudeService()
    return _claude


def _get_deepseek() -> DeepSeekService:
    global _deepseek
    if _deepseek is None:
        _deepseek = DeepSeekService()
    return _deepseek


def get_ai_service(model: str) -> BaseAIService:
    """
    Выбор провайдера по префиксу имени модели.

    - 'deepseek-*'  → DeepSeekService (с fallback на Claude, если ключ не задан)
    - всё остальное → ClaudeService
    """
    model_lower = (model or "").lower()
    if model_lower.startswith("deepseek"):
        if not settings.deepseek_api_key:
            logger.warning(
                f"DEEPSEEK_API_KEY не задан — fallback на Claude для модели '{model}'"
            )
            return _get_claude()
        return _get_deepseek()
    return _get_claude()
