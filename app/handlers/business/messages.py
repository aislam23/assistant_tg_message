"""
Handler-ы для business_message / edited_business_message / deleted_business_messages.

Ядро логики автоответа:
  1) определяем, от владельца или от клиента пришло сообщение
     (`message.from_user.id == connection.user_id`);
  2) сохраняем в messages;
  3) если от клиента — буферизируем и запускаем отложенную генерацию ответа;
  4) если от владельца — молчим (чтобы не зацикливаться).

Отложенная генерация (`_process_aggregated_message`) открывает собственную
сессию БД, т.к. сессия middleware к моменту срабатывания буфера уже закрыта.
"""
import asyncio
from contextlib import suppress
from typing import Any, Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.types import BusinessMessagesDeleted, Message
from loguru import logger

from app.config import settings
from app.database import db
from app.repositories import BusinessRepository
from app.services.ai import get_ai_service
from app.services.context_manager import ContextManager
from app.services.human_response import HumanResponseService, human_response


router = Router(name="business_messages")


# ---------------------------------------------------------------------------
# Основной handler текстовых business-сообщений
# ---------------------------------------------------------------------------


@router.business_message(F.text)
async def handle_business_text(
    message: Message,
    bot: Bot,
    repo: BusinessRepository,
    get_ai_service: Callable[[str], Any],
    context_manager: ContextManager,
    human_response: HumanResponseService,
) -> None:
    """Главный обработчик текстовых сообщений в Business-чате."""
    bc_id = message.business_connection_id
    if not bc_id:
        return

    conn = await repo.get_connection(bc_id)
    if not conn or not conn.is_enabled or not conn.can_reply:
        return

    owner_user_id = conn.user_id
    client_chat_id = message.chat.id
    is_from_owner = (message.from_user and message.from_user.id == owner_user_id)

    # Гарантируем наличие Conversation
    client_name = message.from_user.full_name if message.from_user else None
    conv = await repo.get_or_create_conversation(
        business_connection_id=conn.connection_id,
        owner_user_id=owner_user_id,
        client_chat_id=client_chat_id,
        client_name=client_name,
    )

    text = message.text or ""

    if is_from_owner:
        # Владелец ответил сам — логируем как assistant, followup-за ним,
        # но НЕ отвечаем ничего от AI.
        await repo.add_message(
            conversation_id=conv.id,
            role="assistant",
            content=text,
            telegram_message_id=message.message_id,
        )
        await repo.update_conversation_last_message(
            conversation_id=conv.id,
            role="assistant",
            followup_delay_minutes=settings.followup_delay_minutes
            if settings.followup_enabled
            else None,
        )
        logger.info(f"Owner replied manually in conversation {conv.id} — bot stays silent")
        return

    # --- Сообщение от клиента ---
    await repo.add_message(
        conversation_id=conv.id,
        role="user",
        content=text,
        telegram_message_id=message.message_id,
    )
    await repo.update_conversation_last_message(
        conversation_id=conv.id,
        role="user",
    )

    if settings.human_response_enabled:
        # Буферизация + задержка + typing → _process_aggregated_message
        await human_response.add_message(
            key=(owner_user_id, client_chat_id),
            text=text,
            process_callback=_process_aggregated_message,
            bot=bot,
            business_connection_id=conn.connection_id,
            owner_user_id=owner_user_id,
            client_chat_id=client_chat_id,
            conversation_id=conv.id,
        )
    else:
        # Сразу, без имитации
        await _process_immediate_response(
            bot=bot,
            business_connection_id=conn.connection_id,
            owner_user_id=owner_user_id,
            client_chat_id=client_chat_id,
            conversation_id=conv.id,
            message_text=text,
        )


# ---------------------------------------------------------------------------
# Стабы для нетекстовых событий
# ---------------------------------------------------------------------------


@router.business_message(~F.text)
async def handle_business_non_text(message: Message) -> None:
    """Нетекстовые business-сообщения пока только логируем."""
    logger.info(f"business non-text message skipped: type={message.content_type}")


@router.edited_business_message()
async def handle_edited_business(message: Message) -> None:
    """Редактирование пока только логируем (TODO: обновлять content в messages)."""
    logger.info(f"business message edited: id={message.message_id}")


@router.deleted_business_messages()
async def handle_deleted_business(event: BusinessMessagesDeleted) -> None:
    """Удаление пока только логируем (TODO: soft-delete в messages)."""
    try:
        ids = list(event.message_ids)
    except Exception:
        ids = []
    logger.info(f"business messages deleted: {ids}")


# ---------------------------------------------------------------------------
# Генерация и отправка AI-ответа
# ---------------------------------------------------------------------------


async def _process_aggregated_message(
    *,
    aggregated_text: str,
    bot: Bot,
    business_connection_id: str,
    owner_user_id: int,
    client_chat_id: int,
    conversation_id: int,
) -> None:
    """
    Срабатывает после истечения буфера HumanResponseService.
    Создаёт собственную сессию БД, генерирует AI-ответ, включает typing-цикл
    и отправляет сообщение от имени владельца.
    """
    async with db.session_maker() as session:
        repo = BusinessRepository(session)

        user = await repo.get_user_with_settings(owner_user_id)
        if user is None:
            logger.error(f"User {owner_user_id} not found — aborting AI response")
            return

        model = user.ai_model or settings.claude_model
        ai_service = get_ai_service(model)

        history_limit = user.max_history_messages or settings.max_history_messages
        history = await repo.get_conversation_history(conversation_id, limit=history_limit)
        knowledge = await repo.get_user_knowledge_texts(owner_user_id)

        ctx_manager = ContextManager()
        system_blocks, trimmed_history = ctx_manager.prepare_context_with_cache(
            base_prompt=ai_service.get_default_base_prompt(),
            user_instruction=user.system_prompt,
            knowledge_texts=knowledge,
            history=history,
            current_message=aggregated_text,
            ai_service=ai_service,
        )

        # trimmed_history уже не включает только что сохранённое сообщение клиента
        # как «current_message» — история содержит всё, что есть в БД.
        messages_payload = list(trimmed_history)

        try:
            reply_text = await ai_service.generate_response(
                system_prompt=system_blocks,
                messages=messages_payload,
                model=model,
            )
        except Exception:
            logger.exception(f"AI generation failed for conversation {conversation_id}")
            return

        reply_text = (reply_text or "").strip()
        if not reply_text:
            logger.warning(f"AI returned empty response for conversation {conversation_id}")
            return

        # Имитация «печатаю» с typing-индикатором
        duration = human_response.calculate_typing_duration(reply_text)
        typing_task = asyncio.create_task(
            human_response.typing_loop(
                bot=bot,
                chat_id=client_chat_id,
                business_connection_id=business_connection_id,
                duration=duration,
            )
        )
        try:
            await asyncio.sleep(duration)
        finally:
            typing_task.cancel()
            with suppress(asyncio.CancelledError):
                await typing_task

        # Отправка ответа от имени владельца
        try:
            sent = await bot.send_message(
                chat_id=client_chat_id,
                text=reply_text,
                business_connection_id=business_connection_id,
            )
        except Exception:
            logger.exception(f"Failed to send business message for conversation {conversation_id}")
            return

        await repo.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=reply_text,
            telegram_message_id=sent.message_id,
            token_count=ai_service.count_tokens(reply_text),
        )
        await repo.update_conversation_last_message(
            conversation_id=conversation_id,
            role="assistant",
            followup_delay_minutes=settings.followup_delay_minutes
            if settings.followup_enabled
            else None,
        )
        logger.info(f"✉️  AI-ответ отправлен для conversation {conversation_id}")


async def _process_immediate_response(
    *,
    bot: Bot,
    business_connection_id: str,
    owner_user_id: int,
    client_chat_id: int,
    conversation_id: int,
    message_text: str,
) -> None:
    """
    Упрощённая версия без буфера и typing-loop — сразу генерируем ответ.
    Используется, если HUMAN_RESPONSE_ENABLED=false.
    """
    await _process_aggregated_message(
        aggregated_text=message_text,
        bot=bot,
        business_connection_id=business_connection_id,
        owner_user_id=owner_user_id,
        client_chat_id=client_chat_id,
        conversation_id=conversation_id,
    )
