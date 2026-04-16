"""
Фоновая задача: раз в FOLLOWUP_CHECK_INTERVAL секунд ищет диалоги, которым
пора отправить follow-up-напоминание, и отправляет их от имени владельца.

Запускается в on_startup(bot), останавливается в on_shutdown(bot).
Если FOLLOWUP_ENABLED=false — не стартует вообще.
"""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from loguru import logger

from app.config import settings
from app.database import db
from app.database.models import BusinessConnection, Conversation, User
from app.repositories import BusinessRepository
from app.services.ai import get_ai_service
from app.services.context_manager import ContextManager
from app.services.human_response import human_response


# Отдельный базовый промпт для follow-up. Используется вместо обычного
# get_default_base_prompt(), когда мы решаем напомнить о себе клиенту.
FOLLOWUP_SYSTEM_PROMPT = (
    "Ты — владелец аккаунта. Клиент не ответил на твоё последнее сообщение "
    "в текущем диалоге. Напиши одно короткое ненавязчивое follow-up-сообщение, "
    "опираясь на контекст диалога: уточни остались ли вопросы, предложи помощь "
    "или напомни о теме. Пиши от первого лица, как живой человек. "
    "Не извиняйся за беспокойство. Не представляйся заново. "
    "Одно сообщение, без приветствий вроде «здравствуйте», максимум 2 предложения."
)


class FollowupScheduler:
    """Фоновая корутина, отправляющая follow-up-сообщения."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not settings.followup_enabled:
            logger.info("Follow-up scheduler disabled by config")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("✅ Follow-up scheduler started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("✅ Follow-up scheduler stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Follow-up loop tick failed")

            # sleep с прерыванием при cancel
            try:
                await asyncio.sleep(settings.followup_check_interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """Один проход: выбрать кандидатов и отправить им follow-up."""
        async with db.session_maker() as session:
            repo = BusinessRepository(session)
            now = datetime.now(timezone.utc)
            rows = await repo.get_conversations_for_followup(
                now=now,
                max_count=settings.followup_max_count,
            )
            if rows:
                logger.info(f"Follow-up: found {len(rows)} candidate conversation(s)")

            for conv, user, bc in rows:
                if not bc.is_enabled or not bc.can_reply:
                    continue
                try:
                    await self._send_followup(repo, conv, user, bc)
                except Exception:
                    logger.exception(f"Follow-up failed for conversation {conv.id}")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def _send_followup(
        self,
        repo: BusinessRepository,
        conv: Conversation,
        user: User,
        bc: BusinessConnection,
    ) -> None:
        """Генерирует AI-ответ для follow-up и отправляет его."""
        model = user.ai_model or settings.claude_model
        ai_service = get_ai_service(model)

        history_limit = user.max_history_messages or settings.max_history_messages
        history = await repo.get_conversation_history(conv.id, limit=history_limit)
        knowledge = await repo.get_user_knowledge_texts(user.id)

        ctx_manager = ContextManager()
        system_blocks, trimmed_history = ctx_manager.prepare_context_with_cache(
            base_prompt=FOLLOWUP_SYSTEM_PROMPT,
            user_instruction=user.system_prompt,
            knowledge_texts=knowledge,
            history=history,
            current_message="",
            ai_service=ai_service,
        )

        if not trimmed_history:
            # Не на что делать follow-up — истории нет.
            logger.info(f"Follow-up skipped for conversation {conv.id}: empty history")
            return

        try:
            reply_text = await ai_service.generate_response(
                system_prompt=system_blocks,
                messages=trimmed_history,
                model=model,
            )
        except Exception:
            logger.exception(f"AI generation failed during follow-up for conv {conv.id}")
            return

        reply_text = (reply_text or "").strip()
        if not reply_text:
            logger.warning(f"AI returned empty follow-up for conversation {conv.id}")
            return

        # typing-цикл перед отправкой
        duration = human_response.calculate_typing_duration(reply_text)
        typing_task = asyncio.create_task(
            human_response.typing_loop(
                bot=self.bot,
                chat_id=conv.client_chat_id,
                business_connection_id=bc.connection_id,
                duration=duration,
            )
        )
        try:
            await asyncio.sleep(duration)
        finally:
            typing_task.cancel()
            with suppress(asyncio.CancelledError):
                await typing_task

        try:
            sent = await self.bot.send_message(
                chat_id=conv.client_chat_id,
                text=reply_text,
                business_connection_id=bc.connection_id,
            )
        except Exception:
            logger.exception(f"Failed to send follow-up for conv {conv.id}")
            return

        await repo.add_message(
            conversation_id=conv.id,
            role="assistant",
            content=reply_text,
            telegram_message_id=sent.message_id,
            token_count=ai_service.count_tokens(reply_text),
        )
        await repo.increment_followup_count(conv.id)
        # Планируем next_followup_at на следующий цикл, если лимит не исчерпан
        # (increment_followup_count уже обнулил next_followup_at при достижении max).
        await repo.update_conversation_last_message(
            conversation_id=conv.id,
            role="assistant",
            followup_delay_minutes=settings.followup_delay_minutes,
        )
        logger.info(f"📬 Follow-up sent for conversation {conv.id}")
