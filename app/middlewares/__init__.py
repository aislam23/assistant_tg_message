"""
Middlewares package
"""
from aiogram import Dispatcher

from .business import BusinessMiddleware
from .logging import LoggingMiddleware
from .user import UserMiddleware


def setup_middlewares(dp: Dispatcher) -> None:
    """Настройка всех middleware"""
    # Обычные события (личные чаты с ботом)
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())

    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    # Business-события — UserMiddleware НЕ вешаем, иначе клиенты владельца
    # попадут в таблицу users.
    biz = BusinessMiddleware()
    dp.business_connection.middleware(biz)
    dp.business_message.middleware(biz)
    dp.edited_business_message.middleware(biz)
    dp.deleted_business_messages.middleware(biz)

    dp.business_connection.middleware(LoggingMiddleware())
    dp.business_message.middleware(LoggingMiddleware())
