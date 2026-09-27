"""Сохранённые голоса: список, добавление, переключение, удаление."""
from __future__ import annotations

import re

from aiogram import F, Router, html
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Storage
from ..keyboards import VoiceCB, voices_keyboard
from ..tts import ProviderRegistry
from ._ui import safe_edit_markup, safe_edit_text

router = Router(name="voices")

MAX_VOICES = 50
VOICE_REF_RE = re.compile(r"^[A-Za-z0-9_\-:.]{4,128}$")
# Пользователь может прислать ссылку вида https://fish.audio/m/<id>/
FISH_URL_RE = re.compile(r"fish\.audio/(?:m|models?)/([A-Za-z0-9_\-]+)")


class AddVoice(StatesGroup):
    name = State()
    ref = State()


def _extract_ref(raw: str) -> str:
    raw = raw.strip()
    match = FISH_URL_RE.search(raw)
    if match:
        return match.group(1)
    return raw.rstrip("/").split("/")[-1].strip()


@router.message(Command("voices"))
async def cmd_voices(message: Message, storage: Storage, registry: ProviderRegistry) -> None:
    assert message.from_user
    state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(state.active_provider)
    voices = await storage.list_voices(message.from_user.id, provider.id)

    if not voices:
        await message.answer(
            f"Для «{html.quote(provider.title)}» пока нет сохранённых голосов.\n"
            "Добавьте первый: /addvoice"
        )
        return

    await message.answer(
        f"Голоса для <b>{html.quote(provider.title)}</b> — нажмите, чтобы сделать активным:",
        reply_markup=voices_keyboard(voices, state.active_voice_id),
    )


@router.callback_query(VoiceCB.filter(F.action == "use"))
async def cb_use_voice(
    query: CallbackQuery, callback_data: VoiceCB, storage: Storage
) -> None:
    assert query.from_user
    voice = await storage.get_voice(callback_data.voice_id)
    if voice is None or voice.user_id != query.from_user.id:
        await query.answer("Голос не найден", show_alert=True)
        return

    await storage.update_user(query.from_user.id, active_voice_id=voice.id)
    state = await storage.get_user(query.from_user.id)
    voices = await storage.list_voices(query.from_user.id, voice.provider)

    await query.answer(f"Активен: {voice.name}")
    await safe_edit_markup(query.message, voices_keyboard(voices, state.active_voice_id))


@router.message(Command("addvoice"))
async def cmd_addvoice(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    storage: Storage,
    registry: ProviderRegistry,
) -> None:
    assert message.from_user
    user_state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)

    existing = await storage.list_voices(message.from_user.id, provider.id)
    if len(existing) >= MAX_VOICES:
        await message.answer(f"Достигнут лимит в {MAX_VOICES} голосов. Удалите лишние: /delvoice")
        return

    # Быстрый вариант в одну строку: /addvoice Имя voice_id
    if command.args:
        parts = command.args.rsplit(maxsplit=1)
        if len(parts) == 2:
            await _save_voice(message, storage, provider.id, parts[0], _extract_ref(parts[1]))
            return
        await message.answer(
            "Формат: <code>/addvoice Имя голоса voice_id</code>\n"
            "Или просто отправьте /addvoice и следуйте подсказкам."
        )
        return

    await state.set_state(AddVoice.name)
    await state.update_data(provider=provider.id)
    await message.answer(
        f"Добавляем голос для <b>{html.quote(provider.title)}</b>.\n\n"
        "Шаг 1/2. Как назвать голос? (например: <i>Диктор</i>)\n"
        "Отмена — /cancel"
    )


@router.message(AddVoice.name, F.text)
async def add_voice_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 48:
        await message.answer("Имя должно быть от 1 до 48 символов. Попробуйте ещё раз.")
        return
    await state.update_data(name=name)
    await state.set_state(AddVoice.ref)
    await message.answer(
        "Шаг 2/2. Пришлите voice id голоса.\n\n"
        "Это либо сам id, либо ссылка вида\n"
        "<code>https://fish.audio/m/&lt;voice_id&gt;</code>"
    )


@router.message(AddVoice.ref, F.text)
async def add_voice_ref(message: Message, state: FSMContext, storage: Storage) -> None:
    ref = _extract_ref(message.text or "")
    if not VOICE_REF_RE.match(ref):
        await message.answer(
            "Не похоже на voice id. Пришлите идентификатор голоса или ссылку на него."
        )
        return
    data = await state.get_data()
    await state.clear()
    await _save_voice(message, storage, data["provider"], data["name"], ref)


async def _save_voice(
    message: Message, storage: Storage, provider_id: str, name: str, ref: str
) -> None:
    assert message.from_user
    if not VOICE_REF_RE.match(ref):
        await message.answer("Не похоже на voice id — проверьте значение.")
        return

    voice = await storage.add_voice(message.from_user.id, provider_id, name.strip(), ref)
    await storage.update_user(message.from_user.id, active_voice_id=voice.id)
    await message.answer(
        f"Голос <b>{html.quote(voice.name)}</b> сохранён и сделан активным.\n"
        f"voice id: <code>{html.quote(voice.voice_ref)}</code>\n\n"
        "Проверить: /test"
    )


@router.message(Command("delvoice"))
async def cmd_delvoice(message: Message, storage: Storage, registry: ProviderRegistry) -> None:
    assert message.from_user
    user_state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)
    voices = await storage.list_voices(message.from_user.id, provider.id)
    if not voices:
        await message.answer("Удалять нечего — сохранённых голосов нет.")
        return
    await message.answer(
        "Какой голос удалить?",
        reply_markup=voices_keyboard(voices, user_state.active_voice_id, mode="delete"),
    )


@router.callback_query(VoiceCB.filter(F.action == "delete"))
async def cb_delete_voice(
    query: CallbackQuery, callback_data: VoiceCB, storage: Storage
) -> None:
    assert query.from_user
    voice = await storage.get_voice(callback_data.voice_id)
    if voice is None or voice.user_id != query.from_user.id:
        await query.answer("Голос не найден", show_alert=True)
        return

    await storage.delete_voice(query.from_user.id, voice.id)
    remaining = await storage.list_voices(query.from_user.id, voice.provider)
    user_state = await storage.get_user(query.from_user.id)

    await query.answer(f"Удалён: {voice.name}")
    if remaining:
        await safe_edit_markup(
            query.message, voices_keyboard(remaining, user_state.active_voice_id, mode="delete")
        )
    else:
        await safe_edit_text(query.message, "Все голоса удалены.")
