"""
Middleware для Telegram Business-событий.

Открывает AsyncSession из общего session_maker, собирает BusinessRepository и
инъецирует зависимости (repo, фабрика AI, context manager, human_response
singleton) в data handler-а.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database import db
from app.repositories import BusinessRepository
from app.services.ai import get_ai_service
from app.services.context_manager import ContextManager
from app.services.human_response import human_response


class BusinessMiddleware(BaseMiddleware):
    """Инъектирует зависимости в handler-ы business-событий."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with db.session_maker() as session:
            data["repo"] = BusinessRepository(session)
            data["get_ai_service"] = get_ai_service
            data["context_manager"] = ContextManager()
            data["human_response"] = human_response
            return await handler(event, data)
