"""Инлайн-клавиатуры и callback-данные."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import Voice
from .tts import TTSProvider


class VoiceCB(CallbackData, prefix="voice"):
    action: str  # use | delete | confirm_delete
    voice_id: int


class ProviderCB(CallbackData, prefix="prov"):
    action: str  # use | setkey | delkey
    provider: str


class FormatCB(CallbackData, prefix="fmt"):
    value: str


def voices_keyboard(voices: list[Voice], active_voice_id: int | None, *, mode: str = "use") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for voice in voices:
        mark = "✅ " if voice.id == active_voice_id and mode == "use" else ""
        prefix = "🗑 " if mode == "delete" else ""
        kb.button(
            text=f"{mark}{prefix}{voice.name}",
            callback_data=VoiceCB(action=mode, voice_id=voice.id),
        )
    kb.adjust(2)
    return kb.as_markup()


def providers_keyboard(
    providers: list[TTSProvider], active: str, configured: set[str]
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for provider in providers:
        mark = "✅ " if provider.id == active else ""
        key = "🔑" if provider.id in configured else "⚠️"
        kb.button(
            text=f"{mark}{provider.title} {key}",
            callback_data=ProviderCB(action="use", provider=provider.id),
        )
    kb.adjust(1)
    return kb.as_markup()


def formats_keyboard(supported: tuple[str, ...], active: str) -> InlineKeyboardMarkup:
    labels = {
        "mp3": "MP3 — файлом",
        "opus": "OGG/Opus — голосовым",
        "wav": "WAV — без сжатия",
    }
    kb = InlineKeyboardBuilder()
    for fmt in supported:
        mark = "✅ " if fmt == active else ""
        kb.button(text=f"{mark}{labels.get(fmt, fmt)}", callback_data=FormatCB(value=fmt))
    kb.adjust(1)
    return kb.as_markup()


def link_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])
