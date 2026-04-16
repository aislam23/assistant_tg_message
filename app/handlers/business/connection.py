"""
Handler события business_connection: бот подключён/отключён к бизнес-аккаунту.
"""
from aiogram import Bot, Router
from aiogram.types import BusinessConnection
from loguru import logger

from app.database import db
from app.repositories import BusinessRepository


router = Router(name="business_connection")


@router.business_connection()
async def handle_business_connection(
    business_connection: BusinessConnection,
    bot: Bot,
    repo: BusinessRepository,
) -> None:
    """
    Обрабатывает подключение/отключение бота к Business-аккаунту владельца.
    Сохраняет строку в business_connections и отправляет владельцу
    приветствие/уведомление в его приват с ботом (user_chat_id).
    """
    # В разных версиях Bot API флаг прав отправки приходит через rights или can_reply
    can_reply = _extract_can_reply(business_connection)

    if business_connection.is_enabled:
        # Убеждаемся, что владелец есть в users (иначе FK упадёт)
        user = business_connection.user
        await db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        await repo.create_or_update_connection(
            connection_id=business_connection.id,
            user_id=user.id,
            user_chat_id=business_connection.user_chat_id,
            is_enabled=True,
            can_reply=can_reply,
        )

        logger.info(
            f"✅ Business подключение включено: connection_id={business_connection.id}, "
            f"user_id={user.id}, can_reply={can_reply}"
        )

        if can_reply:
            greeting = (
                "🤖 <b>Business-режим подключён!</b>\n\n"
                "Теперь я буду отвечать клиентам от вашего имени, имитируя "
                "живое общение: с небольшой паузой, «печатает...» и объединяя "
                "несколько сообщений подряд в один ответ.\n\n"
                "Если вы сами напишете клиенту — я замолчу и передам инициативу вам."
            )
        else:
            greeting = (
                "⚠️ Я подключён к вашему Business-аккаунту, но у меня нет права "
                "отправлять сообщения.\n\n"
                "Откройте Settings → Business → Chatbots и выдайте полные права, "
                "чтобы я мог отвечать клиентам."
            )

        try:
            await bot.send_message(business_connection.user_chat_id, greeting)
        except Exception as e:
            logger.warning(f"Не удалось отправить приветствие владельцу: {e}")

    else:
        await repo.disable_connection(business_connection.id)
        logger.info(f"🔌 Business подключение отключено: {business_connection.id}")
        try:
            await bot.send_message(
                business_connection.user_chat_id,
                "🔌 Business-режим отключён. Больше не буду отвечать клиентам.",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление об отключении: {e}")


def _extract_can_reply(bc: BusinessConnection) -> bool:
    """
    В Bot API поле с правами называется по-разному в разных версиях:
    - старые: can_reply (bool)
    - новые: rights.can_reply (BusinessBotRights)
    Берём то, что доступно.
    """
    # Новая форма — объект rights
    rights = getattr(bc, "rights", None)
    if rights is not None:
        can_reply = getattr(rights, "can_reply", None)
        if can_reply is not None:
            return bool(can_reply)
    # Старая форма — прямое поле
    return bool(getattr(bc, "can_reply", False))
