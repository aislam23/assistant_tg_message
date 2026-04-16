"""
Сборный router для Telegram Business mode.
"""
from aiogram import Router

from .connection import router as connection_router
from .messages import router as messages_router

business_router = Router(name="business")
business_router.include_router(connection_router)
business_router.include_router(messages_router)

__all__ = ["business_router"]
