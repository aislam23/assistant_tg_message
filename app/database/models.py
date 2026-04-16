"""
Модели базы данных
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, DateTime, String, Boolean, Integer, Text, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


class User(Base):
    """Модель пользователя"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Поля для Telegram Business mode (заполняются через админ-SQL до появления UI)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    max_history_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"


class BotStats(Base):
    """Модель статистики бота"""

    __tablename__ = "bot_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_users: Mapped[int] = mapped_column(Integer, default=0)
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    last_restart: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<BotStats(total_users={self.total_users}, status={self.status})>"


class MigrationHistory(Base):
    """Модель для отслеживания примененных миграций"""

    __tablename__ = "migration_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    execution_time: Mapped[Optional[float]] = mapped_column(nullable=True)  # время выполнения в секундах

    def __repr__(self) -> str:
        return f"<MigrationHistory(version={self.version}, name={self.name})>"


# =========================================================================
# Telegram Business mode
# =========================================================================


class BusinessConnection(Base):
    """
    Подключение бота к бизнес-аккаунту владельца.
    Одна запись на business_connection.id от Telegram.
    """

    __tablename__ = "business_connections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # Telegram's business_connection.id
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # приват с владельцем
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_business_connections_user_id", "user_id"),
        Index("idx_business_connections_enabled", "is_enabled"),
    )

    def __repr__(self) -> str:
        return f"<BusinessConnection(connection_id={self.connection_id}, user_id={self.user_id})>"


class Conversation(Base):
    """
    Диалог владельца с конкретным клиентом в рамках business-подключения.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    next_followup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("business_connection_id", "client_chat_id", name="uq_conversations"),
        Index("idx_conversations_owner", "owner_user_id"),
        Index("idx_conversations_bc", "business_connection_id"),
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, owner={self.owner_user_id}, client={self.client_chat_id})>"


class Message(Base):
    """История сообщений в диалоге."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id"),
        Index("idx_messages_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, conv={self.conversation_id}, role={self.role})>"


class UserKnowledgeText(Base):
    """
    Кастомная база знаний владельца — тексты, которые попадают в system_prompt
    для AI при ответе клиенту. Плейсхолдер под будущий админ-UI.
    """

    __tablename__ = "user_knowledge_texts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_knowledge_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<UserKnowledgeText(id={self.id}, user={self.user_id})>"
