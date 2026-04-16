"""
Менеджер контекста: готовит system-блоки и обрезает историю под бюджет токенов.

Для Claude формат system — список блоков с опциональным cache_control
(ephemeral) для prompt caching. Для DeepSeek провайдер сам схлопнет список в
единую строку.
"""
from typing import List, Optional, Tuple

from app.config import settings
from app.database.models import Message
from app.services.ai.base import BaseAIService


# Минимальный размер кэшируемого блока Claude, при котором prompt cache работает.
CLAUDE_CACHE_MIN_TOKENS = 1024


class ContextManager:
    """Собирает system-блоки и обрезает историю под бюджет токенов."""

    def prepare_context_with_cache(
        self,
        base_prompt: str,
        user_instruction: Optional[str],
        knowledge_texts: List[str],
        history: List[Message],
        current_message: str,
        ai_service: BaseAIService,
    ) -> Tuple[List[dict], List[dict]]:
        """
        Возвращает (system_blocks, trimmed_history).

        system_blocks — список блоков в формате Claude:
          [{"type": "text", "text": ..., "cache_control": {...}}, ...]
        Стабильный контент (base_prompt, knowledge) идёт первым и помечается
        cache_control=ephemeral. Пользовательская инструкция — последним
        блоком без кэша (меняется чаще).

        trimmed_history — сообщения в формате [{"role", "content"}], обрезанные
        с хвоста под лимит max_history_messages и бюджет токенов.
        """
        # --- 1. Собираем knowledge под лимит ---
        knowledge_block_text = self._pack_knowledge(knowledge_texts, ai_service)

        # --- 2. Формируем system_blocks ---
        static_tokens = (
            ai_service.count_tokens(base_prompt)
            + ai_service.count_tokens(knowledge_block_text)
        )
        use_cache = (
            settings.enable_prompt_cache
            and static_tokens >= CLAUDE_CACHE_MIN_TOKENS
        )

        system_blocks: List[dict] = []
        base_block: dict = {"type": "text", "text": base_prompt}
        if use_cache:
            base_block["cache_control"] = {"type": "ephemeral"}
        system_blocks.append(base_block)

        if knowledge_block_text:
            knowledge_block: dict = {"type": "text", "text": knowledge_block_text}
            if use_cache:
                knowledge_block["cache_control"] = {"type": "ephemeral"}
            system_blocks.append(knowledge_block)

        if user_instruction:
            # Динамический блок — без cache_control.
            system_blocks.append({"type": "text", "text": user_instruction})

        # --- 3. Обрезаем историю по числу сообщений ---
        max_msgs = settings.max_history_messages
        if len(history) > max_msgs:
            history = history[-max_msgs:]

        # --- 4. Обрезаем историю по токен-бюджету ---
        history_payload = [{"role": m.role, "content": m.content} for m in history]
        budget = settings.max_context_tokens - settings.context_reserve_tokens

        def _tokens_total() -> int:
            system_tokens = sum(
                ai_service.count_tokens(b.get("text", "")) for b in system_blocks
            )
            history_tokens = sum(
                ai_service.count_tokens(m["content"]) for m in history_payload
            )
            current_tokens = ai_service.count_tokens(current_message)
            return system_tokens + history_tokens + current_tokens

        # Отрезаем попарно (user+assistant) самые старые, пока не влезет.
        while _tokens_total() > budget and len(history_payload) > 0:
            # Дропаем 2 самых старых сообщения (или 1, если осталось одно).
            drop = 2 if len(history_payload) >= 2 else 1
            del history_payload[:drop]

        return system_blocks, history_payload

    def _pack_knowledge(
        self,
        knowledge_texts: List[str],
        ai_service: BaseAIService,
    ) -> str:
        """
        Собирает тексты знаний в один блок, ограничивая суммарное число токенов
        лимитом settings.max_knowledge_tokens. Тексты, не влезающие целиком,
        отбрасываются (не режем середину — теряет смысл).
        """
        if not knowledge_texts:
            return ""

        limit = settings.max_knowledge_tokens
        accumulated: List[str] = []
        total = 0
        for chunk in knowledge_texts:
            chunk_tokens = ai_service.count_tokens(chunk)
            if total + chunk_tokens > limit:
                break
            accumulated.append(chunk)
            total += chunk_tokens
        return "\n\n".join(accumulated)
