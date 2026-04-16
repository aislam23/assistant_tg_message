"""
Абстрактный базовый класс AI-провайдера и общий токен-каунтер.
"""
from abc import ABC, abstractmethod
from typing import List, Union

import tiktoken


# Единый offline-каунтер для всех провайдеров. cl100k_base — токенизатор
# GPT-3.5/4, достаточно точен для оценки бюджета контекста на любом LLM.
_ENCODER = tiktoken.get_encoding("cl100k_base")


# Общий базовый промпт — используется, если у пользователя не задан system_prompt.
DEFAULT_BASE_PROMPT = (
    "Ты — личный ассистент владельца аккаунта. Ты общаешься с клиентами "
    "от его имени в его Telegram и отвечаешь от первого лица, как будто "
    "пишет сам владелец. Пиши естественно, лаконично и дружелюбно, "
    "без канцелярита и без представлений про себя как про бота. "
    "Если вопрос выходит за пределы твоих знаний — честно скажи, "
    "что уточнишь и вернёшься, не придумывай факты."
)


class BaseAIService(ABC):
    """
    Интерфейс провайдера LLM для бизнес-режима.

    system_prompt принимается как list[dict] (формат блоков Claude с возможным
    cache_control) или str. Провайдер DeepSeek схлопывает список в строку;
    Claude передаёт как есть.
    """

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: Union[List[dict], str],
        messages: List[dict],
        model: str,
    ) -> str:
        """Сгенерировать текст-ответ. messages — [{"role": ..., "content": ...}]"""

    def count_tokens(self, text: str) -> int:
        """Оценка количества токенов в произвольном тексте (offline)."""
        if not text:
            return 0
        return len(_ENCODER.encode(text))

    def get_default_base_prompt(self) -> str:
        """Дефолтный базовый системный промпт."""
        return DEFAULT_BASE_PROMPT
