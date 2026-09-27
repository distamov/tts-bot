"""Выбор провайдера, ввод и удаление API-ключей, формат ответа."""
from __future__ import annotations

import logging

from aiogram import F, Router, html
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Storage
from ..keyboards import FormatCB, ProviderCB, formats_keyboard, link_keyboard, providers_keyboard
from ..tts import ProviderRegistry, TTSProvider
from ._ui import safe_edit_markup

log = logging.getLogger(__name__)
router = Router(name="keys")


class SetKey(StatesGroup):
    field = State()


@router.message(Command("provider"))
async def cmd_provider(message: Message, storage: Storage, registry: ProviderRegistry) -> None:
    assert message.from_user
    state = await storage.get_user(message.from_user.id)
    configured = await storage.providers_with_credentials(message.from_user.id)
    await message.answer(
        "Выберите TTS-сервис.\n"
        "🔑 — ключ сохранён, ⚠️ — ключа нет.",
        reply_markup=providers_keyboard(registry.all(), state.active_provider, configured),
    )


@router.callback_query(ProviderCB.filter(F.action == "use"))
async def cb_use_provider(
    query: CallbackQuery, callback_data: ProviderCB, storage: Storage, registry: ProviderRegistry
) -> None:
    assert query.from_user
    try:
        provider = registry.get(callback_data.provider)
    except KeyError:
        await query.answer("Такого провайдера больше нет", show_alert=True)
        return

    # Активный голос привязан к провайдеру — при смене сбрасываем на голос нового провайдера.
    voices = await storage.list_voices(query.from_user.id, provider.id)
    new_voice_id = voices[0].id if voices else None
    await storage.update_user(
        query.from_user.id, active_provider=provider.id, active_voice_id=new_voice_id
    )

    configured = await storage.providers_with_credentials(query.from_user.id)
    await query.answer(f"Активен: {provider.title}")
    await safe_edit_markup(
        query.message, providers_keyboard(registry.all(), provider.id, configured)
    )
    if isinstance(query.message, Message):
        if provider.id not in configured:
            await query.message.answer(
                f"Для «{html.quote(provider.title)}» ещё не задан ключ — /setkey",
                reply_markup=(
                    link_keyboard("Получить ключ", provider.signup_url)
                    if provider.signup_url
                    else None
                ),
            )


@router.message(Command("setkey"))
async def cmd_setkey(
    message: Message, state: FSMContext, storage: Storage, registry: ProviderRegistry
) -> None:
    assert message.from_user
    user_state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)

    await state.set_state(SetKey.field)
    await state.update_data(provider=provider.id, index=0, values={})
    await message.answer(
        f"Настраиваем <b>{html.quote(provider.title)}</b>.\n"
        "Сообщения с ключами я удаляю из чата сразу после сохранения.\n"
        "Отмена — /cancel",
        reply_markup=(
            link_keyboard("Где взять ключ", provider.signup_url) if provider.signup_url else None
        ),
    )
    await _ask_field(message, provider, 0)


async def _ask_field(message: Message, provider: TTSProvider, index: int) -> None:
    field = provider.credential_fields[index]
    total = len(provider.credential_fields)
    lines = [f"Шаг {index + 1}/{total}. {html.quote(field.title)}"]
    if field.hint:
        lines.append(f"<i>{html.quote(field.hint)}</i>")
    if not field.required:
        lines.append(
            f"Необязательно — отправьте <code>-</code>, чтобы оставить "
            f"<code>{html.quote(field.default)}</code>."
        )
    await message.answer("\n".join(lines))


@router.message(SetKey.field, F.text)
async def setkey_field(
    message: Message, state: FSMContext, storage: Storage, registry: ProviderRegistry
) -> None:
    assert message.from_user
    data = await state.get_data()
    provider = registry.get_or_default(data["provider"])
    index: int = data["index"]
    values: dict[str, str] = dict(data["values"])
    field = provider.credential_fields[index]

    raw = (message.text or "").strip()
    if field.secret:
        # Ключ не должен остаться в истории чата.
        try:
            await message.delete()
        except TelegramBadRequest as exc:
            log.warning("Не удалось удалить сообщение с секретом: %s", exc)

    if raw == "-" or not raw:
        if field.required:
            await message.answer(f"«{html.quote(field.title)}» обязательно. Введите значение.")
            return
        values[field.key] = field.default
    else:
        values[field.key] = raw

    index += 1
    if index < len(provider.credential_fields):
        await state.update_data(index=index, values=values)
        await _ask_field(message, provider, index)
        return

    await state.clear()
    try:
        provider.validate_credentials(values)
    except Exception as exc:  # noqa: BLE001 — показываем пользователю причину
        await message.answer(f"Не сохранил: {html.quote(str(exc))}")
        return

    await storage.set_credentials(message.from_user.id, provider.id, values)
    if data["provider"] != (await storage.get_user(message.from_user.id)).active_provider:
        await storage.update_user(message.from_user.id, active_provider=provider.id)

    await message.answer(
        f"Ключ для <b>{html.quote(provider.title)}</b> сохранён (зашифрован на сервере).\n\n"
        "Проверить: /test"
    )


@router.message(Command("delkey"))
async def cmd_delkey(message: Message, storage: Storage, registry: ProviderRegistry) -> None:
    assert message.from_user
    user_state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)
    deleted = await storage.delete_credentials(message.from_user.id, provider.id)
    await message.answer(
        f"Ключ для «{html.quote(provider.title)}» удалён."
        if deleted
        else f"Для «{html.quote(provider.title)}» ключа и не было."
    )


@router.message(Command("format"))
async def cmd_format(message: Message, storage: Storage, registry: ProviderRegistry) -> None:
    assert message.from_user
    user_state = await storage.get_user(message.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)
    await message.answer(
        "В каком виде присылать результат?",
        reply_markup=formats_keyboard(provider.formats, user_state.audio_format),
    )


@router.callback_query(FormatCB.filter())
async def cb_format(
    query: CallbackQuery, callback_data: FormatCB, storage: Storage, registry: ProviderRegistry
) -> None:
    assert query.from_user
    user_state = await storage.get_user(query.from_user.id)
    provider = registry.get_or_default(user_state.active_provider)
    if callback_data.value not in provider.formats:
        await query.answer("Этот формат недоступен у активного провайдера", show_alert=True)
        return

    await storage.update_user(query.from_user.id, audio_format=callback_data.value)
    await query.answer(f"Формат: {callback_data.value}")
    await safe_edit_markup(
        query.message, formats_keyboard(provider.formats, callback_data.value)
    )
