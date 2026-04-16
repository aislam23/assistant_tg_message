"""
Миграция для добавления таблиц Telegram Business mode
и расширения users колонками для настроек AI.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from loguru import logger

from app.database.migrations.base import Migration


class AddBusinessTablesMigration(Migration):
    """
    Добавляет таблицы business_connections, conversations, messages,
    user_knowledge_texts и новые колонки в users (system_prompt, ai_model,
    max_history_messages) для режима Telegram Business.
    """

    def get_version(self) -> str:
        return "20260416_000001"

    def get_description(self) -> str:
        return "Add business connections, conversations, messages, knowledge tables and user AI fields"

    async def check_can_apply(self, connection: AsyncConnection) -> bool:
        """Применяем миграцию если главной таблицы ещё нет."""
        result = await connection.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'business_connections'
            );
        """))
        exists = result.scalar()
        return not exists

    async def upgrade(self, connection: AsyncConnection) -> None:
        """Создание таблиц и расширение users."""

        # --- Расширение users под настройки AI ---
        await connection.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS system_prompt TEXT;"
        ))
        await connection.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_model VARCHAR(64);"
        ))
        await connection.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_history_messages INTEGER;"
        ))

        # --- business_connections ---
        await connection.execute(text("""
            CREATE TABLE business_connections (
                id BIGSERIAL PRIMARY KEY,
                connection_id VARCHAR(255) UNIQUE NOT NULL,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_chat_id BIGINT NOT NULL,
                is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                can_reply BOOLEAN NOT NULL DEFAULT FALSE,
                connected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        await connection.execute(text(
            "CREATE INDEX idx_business_connections_user_id ON business_connections(user_id);"
        ))
        await connection.execute(text(
            "CREATE INDEX idx_business_connections_enabled ON business_connections(is_enabled);"
        ))

        # --- conversations ---
        await connection.execute(text("""
            CREATE TABLE conversations (
                id BIGSERIAL PRIMARY KEY,
                business_connection_id VARCHAR(255) NOT NULL,
                owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_chat_id BIGINT NOT NULL,
                client_name VARCHAR(255),
                last_message_at TIMESTAMP WITH TIME ZONE,
                last_message_role VARCHAR(16),
                next_followup_at TIMESTAMP WITH TIME ZONE,
                followup_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_conversations UNIQUE (business_connection_id, client_chat_id)
            );
        """))
        await connection.execute(text(
            "CREATE INDEX idx_conversations_owner ON conversations(owner_user_id);"
        ))
        await connection.execute(text(
            "CREATE INDEX idx_conversations_bc ON conversations(business_connection_id);"
        ))
        await connection.execute(text(
            "CREATE INDEX idx_conversations_followup ON conversations(next_followup_at) "
            "WHERE next_followup_at IS NOT NULL;"
        ))

        # --- messages ---
        await connection.execute(text("""
            CREATE TABLE messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role VARCHAR(16) NOT NULL,
                content TEXT NOT NULL,
                telegram_message_id BIGINT,
                token_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        await connection.execute(text(
            "CREATE INDEX idx_messages_conversation ON messages(conversation_id);"
        ))
        await connection.execute(text(
            "CREATE INDEX idx_messages_created ON messages(conversation_id, created_at DESC);"
        ))

        # --- user_knowledge_texts (плейсхолдер) ---
        await connection.execute(text("""
            CREATE TABLE user_knowledge_texts (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        await connection.execute(text(
            "CREATE INDEX idx_user_knowledge_user ON user_knowledge_texts(user_id);"
        ))

        logger.info("✅ Created business_connections, conversations, messages, user_knowledge_texts + extended users")

    async def downgrade(self, connection: AsyncConnection) -> None:
        """Откат — удаление таблиц и колонок."""
        await connection.execute(text("DROP TABLE IF EXISTS user_knowledge_texts CASCADE;"))
        await connection.execute(text("DROP TABLE IF EXISTS messages CASCADE;"))
        await connection.execute(text("DROP TABLE IF EXISTS conversations CASCADE;"))
        await connection.execute(text("DROP TABLE IF EXISTS business_connections CASCADE;"))
        await connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS max_history_messages;"))
        await connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS ai_model;"))
        await connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS system_prompt;"))
        logger.info("✅ Rolled back business tables migration")
