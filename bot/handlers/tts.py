"""Главный сценарий: текст → аудио."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router, html
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from ..config import Settings
from ..db import Storage
from ..tts import ProviderRegistry, TTSError, TTSProvider, TTSRequest
from ..utils import (
    audio_extension,
    format_cost,
    found_tags,
    human_bytes,
    safe_filename,
    split_text,
    utf8_bytes,
)

log = logging.getLogger(__name__)
router = Router(name="tts")

TEST_PHRASE = "Проверка связи. [pause] Голос настроен и готов к работе."
MAX_TXT_FILE_BYTES = 200 * 1024


@router.message(Command("test"))
async def cmd_test(
    message: Message,
    storage: Storage,
    registry: ProviderRegistry,
    settings: Settings,
    user_lock: asyncio.Lock,
) -> None:
    await _speak(message, TEST_PHRASE, storage, registry, settings, user_lock)


@router.message(F.document)
async def handle_document(
    message: Message,
    storage: Storage,
    registry: ProviderRegistry,
    settings: Settings,
    user_lock: asyncio.Lock,
) -> None:
    doc = message.document
    assert doc is not None
    name = (doc.file_name or "").lower()
    if not name.endswith(".txt"):
        await message.answer("Умею читать только .txt — пришлите текстовый файл или просто текст.")
        return
    if (doc.file_size or 0) > MAX_TXT_FILE_BYTES:
        await message.answer(f"Файл слишком большой (лимит {MAX_TXT_FILE_BYTES // 1024} КБ).")
        return

    assert message.bot
    buffer = await message.bot.download(doc)
    if buffer is None:
        await message.answer("Не удалось скачать файл.")
        return
    try:
        text = buffer.read().decode("utf-8")
    except UnicodeDecodeError:
        await message.answer("Файл не в UTF-8 — пересохраните его в этой кодировке.")
        return

    await _speak(message, text, storage, registry, settings, user_lock)


@router.message(F.text.startswith("/"))
async def handle_unknown_command(message: Message) -> None:
    await message.answer("Не знаю такой команды. Список — /help")


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(
    message: Message,
    storage: Storage,
    registry: ProviderRegistry,
    settings: Settings,
    user_lock: asyncio.Lock,
) -> None:
    await _speak(message, message.text or "", storage, registry, settings, user_lock)


async def _resolve_credentials(
    user_id: int, provider: TTSProvider, storage: Storage, settings: Settings
) -> dict[str, str] | None:
    creds = await storage.get_credentials(user_id, provider.id)
    if creds:
        return creds
    # Общий ключ из конфигурации сервера — если владелец бота его задал.
    if provider.id == "fish" and settings.default_fish_api_key:
        return {
            "api_key": settings.default_fish_api_key,
            "model": settings.default_fish_model,
        }
    return None


async def _resolve_voice_ref(
    user_id: int, provider: TTSProvider, storage: Storage, settings: Settings
) -> tuple[str | None, str]:
    state = await storage.get_user(user_id)
    if state.active_voice_id:
        voice = await storage.get_voice(state.active_voice_id)
        if voice and voice.provider == provider.id:
            return voice.voice_ref, voice.name
    if provider.id == "fish" and settings.default_fish_voice_id:
        return settings.default_fish_voice_id, "по умолчанию"
    return None, "голос модели"


async def _speak(
    message: Message,
    text: str,
    storage: Storage,
    registry: ProviderRegistry,
    settings: Settings,
    user_lock: asyncio.Lock,
) -> None:
    assert message.from_user
    user_id = message.from_user.id
    text = text.strip()

    if not text:
        await message.answer("Пустой текст — нечего озвучивать.")
        return
    if len(text) > settings.max_text_chars:
        await message.answer(
            f"Текст длиннее лимита: {len(text)} симв. при максимуме "
            f"{settings.max_text_chars}. Разбейте на части."
        )
        return

    if user_lock.locked():
        await message.answer("Уже озвучиваю предыдущий текст — дождитесь результата.")
        return

    async with user_lock:
        user_state = await storage.get_user(user_id)
        provider = registry.get_or_default(user_state.active_provider)

        creds = await _resolve_credentials(user_id, provider, storage, settings)
        if creds is None:
            await message.answer(
                f"Для «{html.quote(provider.title)}» не задан API-ключ.\n"
                "Задайте его командой /setkey."
            )
            return

        voice_ref, voice_name = await _resolve_voice_ref(user_id, provider, storage, settings)
        fmt = user_state.audio_format if user_state.audio_format in provider.formats else "mp3"
        chunks = split_text(text, provider.max_chunk_chars)

        status = await message.answer(
            f"Синтезирую… ({len(chunks)} " + ("фрагмент)" if len(chunks) == 1 else "фрагментов)")
        )
        action = ChatAction.RECORD_VOICE if fmt == "opus" else ChatAction.UPLOAD_DOCUMENT

        parts: list[bytes] = []
        try:
            for index, chunk in enumerate(chunks, start=1):
                await message.bot.send_chat_action(message.chat.id, action)
                if len(chunks) > 1:
                    await _edit(status, f"Синтезирую… {index}/{len(chunks)}")
                audio = await provider.synthesize(
                    TTSRequest(text=chunk, voice_ref=voice_ref, fmt=fmt), creds
                )
                parts.append(audio)
        except TTSError as exc:
            await storage.log_usage(user_id, provider.id, len(text), utf8_bytes(text), ok=False)
            await _edit(status, f"❌ {html.quote(str(exc))}")
            return
        except Exception as exc:  # noqa: BLE001 — не роняем бота из-за одного запроса
            log.exception("Неожиданная ошибка синтеза")
            await storage.log_usage(user_id, provider.id, len(text), utf8_bytes(text), ok=False)
            await _edit(status, f"❌ Внутренняя ошибка: {html.quote(type(exc).__name__)}")
            return

        await storage.log_usage(user_id, provider.id, len(text), utf8_bytes(text), ok=True)
        try:
            await status.delete()
        except TelegramBadRequest:
            pass

        caption = _caption(provider, text, voice_name, fmt, sum(len(p) for p in parts))
        await _send_audio(message, parts, fmt, text, caption)


def _caption(
    provider: TTSProvider, text: str, voice_name: str, fmt: str, size: int
) -> str:
    lines = [
        f"🎙 {html.quote(voice_name)} · {html.quote(provider.title)}",
        f"{len(text)} симв. · {human_bytes(size)} · {fmt}",
    ]
    cost = provider.estimate_cost_usd(text)
    if cost is not None:
        lines.append(f"≈ {format_cost(cost)}")
    tags = found_tags(text)
    if tags and provider.supports_inline_tags:
        lines.append("теги: " + html.quote(" ".join(tags[:8])))
    return "\n".join(lines)


async def _send_audio(
    message: Message, parts: list[bytes], fmt: str, text: str, caption: str
) -> None:
    ext = audio_extension(fmt)

    # MP3-фрагменты склеиваются в один файл; ogg/wav так склеивать нельзя —
    # отправляем их отдельными сообщениями.
    if fmt == "mp3" and len(parts) > 1:
        parts = [b"".join(parts)]

    for index, audio in enumerate(parts, start=1):
        suffix = f" ({index}/{len(parts)})" if len(parts) > 1 else ""
        part_caption = caption + suffix

        async def send(cap: str | None) -> None:
            # BufferedInputFile одноразовый — создаём заново на каждую попытку.
            file = BufferedInputFile(audio, filename=safe_filename(text, ext))
            if fmt == "opus":
                await message.answer_voice(file, caption=cap)
            elif fmt == "mp3":
                await message.answer_audio(
                    file, caption=cap, title=safe_filename(text, ext).rsplit(".", 1)[0]
                )
            else:
                await message.answer_document(file, caption=cap)

        try:
            await send(part_caption)
        except TelegramBadRequest as exc:
            # Аудио уже оплачено — отдаём его без подписи, а не теряем.
            log.warning("Подпись отклонена Telegram (%s), отправляю без неё", exc)
            await send(None)


async def _edit(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except TelegramBadRequest:
        pass
