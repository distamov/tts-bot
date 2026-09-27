"""Мелкие помощники для работы с сообщениями."""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


async def safe_edit_markup(message: Message | None, markup: InlineKeyboardMarkup) -> None:
    """Обновить клавиатуру, не падая, если она и так такая же.

    Telegram отвечает "message is not modified", когда пользователь нажимает
    на уже выбранный пункт — для нас это норма, а не ошибка.
    """
    if not isinstance(message, Message):
        return
    try:
        await message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.warning("Не удалось обновить клавиатуру: %s", exc)


async def safe_edit_text(message: Message | None, text: str) -> None:
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.warning("Не удалось изменить текст: %s", exc)
