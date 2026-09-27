"""Базовые команды: /start, /help, /settings, /cancel, /stats."""
from __future__ import annotations

from aiogram import Router, html
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..config import Settings
from ..db import Storage
from ..tts import ProviderRegistry
from ..utils import format_cost

router = Router(name="common")

HELP = """<b>Бот озвучки текста</b>

Пришлите текст — получите аудио.

<b>Голоса</b>
/voices — список сохранённых голосов и переключение
/addvoice — добавить голос (имя + voice id)
/delvoice — удалить голос

<b>Провайдер и ключи</b>
/provider — выбрать TTS-сервис
/setkey — задать API-ключ активного сервиса
/delkey — удалить сохранённый ключ
/settings — что сейчас настроено

<b>Прочее</b>
/format — формат ответа (файл MP3 или голосовое)
/test — проверить связку «ключ + голос»
/cancel — отменить текущий диалог

<b>Инлайн-теги</b> (Fish Audio)
Внутри текста можно ставить теги — они управляют подачей:
<code>[pause]</code> — пауза
<code>[long pause]</code> — длинная пауза
<code>[excited]</code>, <code>[whisper]</code>, <code>[sad]</code>,
<code>[angry]</code>, <code>[laugh]</code> — эмоция дальнейшей речи

Пример:
<code>Привет! [pause] У меня для тебя [excited] отличные новости.</code>

<b>Где взять voice id</b>
На fish.audio откройте страницу голоса — id виден в адресной строке
(<code>fish.audio/m/&lt;voice_id&gt;</code>). Его и вводите в /addvoice."""


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


@router.message(CommandStart())
async def cmd_start(message: Message, storage: Storage) -> None:
    assert message.from_user
    await storage.get_user(message.from_user.id)
    await message.answer(
        f"Привет, {html.quote(message.from_user.first_name or 'друг')}!\n\n"
        "Пришлите любой текст — верну озвучку.\n"
        "Сначала стоит задать ключ (/setkey) и добавить голос (/addvoice).\n\n"
        "Полная справка — /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    await message.answer("Отменено." if current else "Нечего отменять.")


@router.message(Command("settings"))
async def cmd_settings(
    message: Message, storage: Storage, registry: ProviderRegistry, settings: Settings
) -> None:
    assert message.from_user
    user_id = message.from_user.id
    state = await storage.get_user(user_id)
    provider = registry.get_or_default(state.active_provider)

    creds = await storage.get_credentials(user_id, provider.id)
    if creds is not None:
        creds_line = "\n" + html.quote(provider.describe_credentials(creds))
    elif provider.id == "fish" and settings.default_fish_api_key:
        creds_line = "ключ по умолчанию из конфигурации сервера"
    else:
        creds_line = "⚠️ не задан — /setkey"

    voice = await storage.get_voice(state.active_voice_id) if state.active_voice_id else None
    if voice:
        voice_line = f"{html.quote(voice.name)} (<code>{html.quote(voice.voice_ref)}</code>)"
    elif provider.id == "fish" and settings.default_fish_voice_id:
        voice_line = f"по умолчанию (<code>{html.quote(settings.default_fish_voice_id)}</code>)"
    else:
        voice_line = "голос модели по умолчанию — /addvoice"

    voices = await storage.list_voices(user_id, provider.id)
    usage = await storage.usage_totals(user_id)
    cost = (
        None
        if provider.usd_per_million_bytes is None
        else usage["utf8_bytes"] / 1_000_000 * provider.usd_per_million_bytes
    )

    lines = [
        "<b>Текущие настройки</b>",
        "",
        f"Провайдер: <b>{html.quote(provider.title)}</b>",
        f"Ключ: {creds_line}",
        f"Голос: {voice_line}",
        f"Сохранено голосов: {len(voices)}",
        f"Формат: <b>{state.audio_format}</b>",
        "",
        "<b>Расход</b>",
        f"Запросов: {usage['requests']}",
        f"Символов: {_num(usage['chars'])}",
        f"UTF-8 байт: {_num(usage['utf8_bytes'])}",
        f"Оценка стоимости: {format_cost(cost)}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message, storage: Storage, settings: Settings) -> None:
    assert message.from_user
    if not settings.is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    users = await storage.count_users()
    usage = await storage.usage_totals()
    await message.answer(
        "\n".join(
            [
                "<b>Статистика бота</b>",
                f"Пользователей: {users}",
                f"Успешных синтезов: {usage['requests']}",
                f"Символов: {_num(usage['chars'])}",
                f"UTF-8 байт: {_num(usage['utf8_bytes'])}",
            ]
        )
    )
