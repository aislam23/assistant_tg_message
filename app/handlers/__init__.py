"""
Handlers package
"""
from aiogram import Dispatcher

from .admin import combined_router as admin_router
from .business import business_router
from .help import router as help_router
from .start import router as start_router


def setup_routers(dp: Dispatcher) -> None:
    """Настройка всех роутеров"""
    # Business-события обрабатываются с приоритетом — подключаем первым.
    dp.include_router(business_router)
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(help_router)
