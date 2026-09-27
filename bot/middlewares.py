"""Middleware: контроль доступа и защита от параллельных запросов одного пользователя."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from .config import Settings

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пускает только пользователей из ALLOWED_USER_IDS (если список задан)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if self._settings.is_allowed(user.id):
            return await handler(event, data)

        log.info("Доступ запрещён: user_id=%s username=%s", user.id, user.username)
        text = (
            "Доступ к этому боту ограничен.\n"
            f"Ваш Telegram ID: <code>{user.id}</code> — передайте его владельцу бота."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён", show_alert=True)
        return None


class SingleFlightMiddleware(BaseMiddleware):
    """Не даёт одному пользователю запустить несколько синтезов одновременно."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock_for(self, user_id: int) -> asyncio.Lock:
        return self._locks[user_id]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None:
            data["user_lock"] = self.lock_for(user.id)
        return await handler(event, data)
