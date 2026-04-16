"""
HumanResponseService — буферизация входящих сообщений клиента,
случайная задержка перед ответом и цикл typing-индикатора.

Singleton: `human_response` экспортируется на уровне модуля.
"""
import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from aiogram import Bot
from loguru import logger

from app.config import settings


BufferKey = Tuple[int, int]  # (owner_user_id, client_chat_id)


@dataclass
class MessageBuffer:
    """Буфер сообщений одного клиента + таймер + локальный lock."""
    messages: list[str] = field(default_factory=list)
    timer_task: Optional[asyncio.Task] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class HumanResponseService:
    """Буферизация, задержка ответа и typing-loop."""

    def __init__(self) -> None:
        self._buffers: Dict[BufferKey, MessageBuffer] = {}
        self._global_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Буферизация
    # ------------------------------------------------------------------

    async def add_message(
        self,
        key: BufferKey,
        text: str,
        process_callback: Callable[..., Awaitable[None]],
        **ctx: Any,
    ) -> None:
        """
        Добавляет сообщение в буфер клиента. Если таймер уже запущен — отменяет
        его и стартует новый. Это даёт эффект «ждём, пока человек допишет».
        """
        async with self._global_lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = MessageBuffer()
                self._buffers[key] = buf

        async with buf.lock:
            buf.messages.append(text)
            if buf.timer_task is not None and not buf.timer_task.done():
                buf.timer_task.cancel()
            buf.timer_task = asyncio.create_task(
                self._delay_and_process(key, process_callback, ctx)
            )

    async def _delay_and_process(
        self,
        key: BufferKey,
        callback: Callable[..., Awaitable[None]],
        ctx: dict,
    ) -> None:
        """Ждёт случайное время, объединяет буфер и вызывает callback."""
        delay = random.uniform(settings.min_response_delay, settings.max_response_delay)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            # Таймер перезапущен новым сообщением — тихо выходим.
            return

        # Забираем буфер из словаря, чтобы новые сообщения пошли в свежий буфер.
        async with self._global_lock:
            buf = self._buffers.pop(key, None)
        if buf is None:
            return
        async with buf.lock:
            aggregated = "\n\n".join(buf.messages)

        try:
            await callback(aggregated_text=aggregated, **ctx)
        except Exception:
            logger.exception(f"HumanResponseService callback failed for key={key}")

    # ------------------------------------------------------------------
    # Typing
    # ------------------------------------------------------------------

    def calculate_typing_duration(self, text: str) -> float:
        """
        Оценивает длительность «печати» по длине ответа, добавляя вариативность
        и ограничивая снизу/сверху.
        """
        base = len(text) / max(settings.typing_chars_per_second, 1.0)
        jitter = base * random.uniform(-0.2, 0.2)
        return max(
            settings.typing_min_duration,
            min(settings.typing_max_duration, base + jitter),
        )

    async def typing_loop(
        self,
        bot: Bot,
        chat_id: int,
        business_connection_id: str,
        duration: float,
    ) -> None:
        """
        Отправляет chat_action='typing' раз в ~4 сек в течение duration секунд.
        Telegram сбрасывает typing через 5 сек, поэтому надо обновлять.
        """
        loop = asyncio.get_event_loop()
        end = loop.time() + duration
        while loop.time() < end:
            try:
                await bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                    business_connection_id=business_connection_id,
                )
            except Exception as e:
                logger.warning(f"typing action failed: {e}")
            remaining = end - loop.time()
            await asyncio.sleep(min(4.0, max(0.1, remaining)))


# Singleton для использования из handler-ов и scheduler-а.
human_response = HumanResponseService()


__all__ = ["human_response", "HumanResponseService", "MessageBuffer"]
