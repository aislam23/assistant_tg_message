"""
Репозиторий для Telegram Business mode.

Инкапсулирует все операции с таблицами business_connections, conversations,
messages, user_knowledge_texts и настройками пользователя (User.ai_model и пр.).

Каждый метод сам коммитит свою единицу работы — middleware не нужно об этом знать.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    BusinessConnection,
    Conversation,
    Message,
    User,
    UserKnowledgeText,
)


class BusinessRepository:
    """CRUD для доменных сущностей Business-режима."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # BusinessConnection
    # ------------------------------------------------------------------

    async def create_or_update_connection(
        self,
        connection_id: str,
        user_id: int,
        user_chat_id: int,
        is_enabled: bool,
        can_reply: bool,
    ) -> BusinessConnection:
        """Upsert по connection_id."""
        stmt = select(BusinessConnection).where(
            BusinessConnection.connection_id == connection_id
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.user_id = user_id
            existing.user_chat_id = user_chat_id
            existing.is_enabled = is_enabled
            existing.can_reply = can_reply
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        conn = BusinessConnection(
            connection_id=connection_id,
            user_id=user_id,
            user_chat_id=user_chat_id,
            is_enabled=is_enabled,
            can_reply=can_reply,
        )
        self.session.add(conn)
        await self.session.commit()
        await self.session.refresh(conn)
        return conn

    async def disable_connection(self, connection_id: str) -> None:
        """Выставляет is_enabled=false для заданного connection_id."""
        stmt = (
            update(BusinessConnection)
            .where(BusinessConnection.connection_id == connection_id)
            .values(is_enabled=False)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_connection(self, connection_id: str) -> Optional[BusinessConnection]:
        """Достаёт подключение по его Telegram connection_id."""
        stmt = select(BusinessConnection).where(
            BusinessConnection.connection_id == connection_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    async def get_or_create_conversation(
        self,
        business_connection_id: str,
        owner_user_id: int,
        client_chat_id: int,
        client_name: Optional[str] = None,
    ) -> Conversation:
        """Находит диалог по UNIQUE(business_connection_id, client_chat_id) или создаёт новый."""
        stmt = select(Conversation).where(
            Conversation.business_connection_id == business_connection_id,
            Conversation.client_chat_id == client_chat_id,
        )
        result = await self.session.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv is not None:
            # Обновляем client_name, если пришло более свежее значение
            if client_name and conv.client_name != client_name:
                conv.client_name = client_name
                await self.session.commit()
                await self.session.refresh(conv)
            return conv

        conv = Conversation(
            business_connection_id=business_connection_id,
            owner_user_id=owner_user_id,
            client_chat_id=client_chat_id,
            client_name=client_name,
        )
        self.session.add(conv)
        await self.session.commit()
        await self.session.refresh(conv)
        return conv

    async def update_conversation_last_message(
        self,
        conversation_id: int,
        role: str,
        followup_delay_minutes: Optional[int] = None,
    ) -> None:
        """
        Обновляет метаинформацию о последнем сообщении.

        Если role='assistant' и передано followup_delay_minutes — планируем
        next_followup_at = now + delta, НО только если лимит follow-up-ов
        ещё не исчерпан (followup_count < settings.followup_max_count).
        Если role='user' — сбрасываем next_followup_at и followup_count.
        """
        now = datetime.now(timezone.utc)
        values: dict = {
            "last_message_at": now,
            "last_message_role": role,
        }
        if role == "user":
            values["next_followup_at"] = None
            values["followup_count"] = 0
        elif role == "assistant" and followup_delay_minutes is not None:
            # Проверяем, остался ли лимит под ещё один follow-up.
            current = await self.session.get(Conversation, conversation_id)
            current_count = current.followup_count if current else 0
            if current_count < settings.followup_max_count:
                values["next_followup_at"] = now + timedelta(minutes=followup_delay_minutes)
            else:
                values["next_followup_at"] = None

        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_conversations_for_followup(
        self,
        now: datetime,
        max_count: int,
        limit: int = 50,
    ) -> List[Tuple[Conversation, User, BusinessConnection]]:
        """
        Возвращает диалоги, которым пора отправить follow-up:
          - last_message_role='assistant'
          - next_followup_at <= now
          - followup_count < max_count
        JOIN-ит users и business_connections для удобства планировщика.
        """
        stmt = (
            select(Conversation, User, BusinessConnection)
            .join(User, User.id == Conversation.owner_user_id)
            .join(
                BusinessConnection,
                BusinessConnection.connection_id == Conversation.business_connection_id,
            )
            .where(
                Conversation.last_message_role == "assistant",
                Conversation.next_followup_at.is_not(None),
                Conversation.next_followup_at <= now,
                Conversation.followup_count < max_count,
                BusinessConnection.is_enabled.is_(True),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def increment_followup_count(self, conversation_id: int) -> None:
        """
        Инкрементирует followup_count. Если достиг предела — очищает next_followup_at,
        чтобы диалог больше не попадал в выборку.
        """
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        result = await self.session.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv is None:
            return
        conv.followup_count = (conv.followup_count or 0) + 1
        if conv.followup_count >= settings.followup_max_count:
            conv.next_followup_at = None
        await self.session.commit()

    # ------------------------------------------------------------------
    # Message
    # ------------------------------------------------------------------

    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        telegram_message_id: Optional[int] = None,
        token_count: int = 0,
    ) -> Message:
        """Добавляет сообщение в историю диалога."""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            telegram_message_id=telegram_message_id,
            token_count=token_count,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def get_conversation_history(
        self,
        conversation_id: int,
        limit: int,
    ) -> List[Message]:
        """
        Последние N сообщений диалога в хронологическом порядке.
        Делаем LIMIT по created_at DESC и разворачиваем список.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows: List[Message] = list(result.scalars().all())
        rows.reverse()
        return rows

    # ------------------------------------------------------------------
    # User / knowledge
    # ------------------------------------------------------------------

    async def get_user_with_settings(self, user_id: int) -> Optional[User]:
        """Достаёт User со всеми колонками (включая AI-настройки)."""
        return await self.session.get(User, user_id)

    async def get_user_knowledge_texts(self, user_id: int) -> List[str]:
        """
        Возвращает тексты пользовательской базы знаний в заданном порядке.
        Плейсхолдер под будущий админ-UI.
        """
        stmt = (
            select(UserKnowledgeText.content)
            .where(UserKnowledgeText.user_id == user_id)
            .order_by(UserKnowledgeText.order_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
