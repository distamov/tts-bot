"""Точка входа. Long polling — работает без белого IP и без домена."""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand, ErrorEvent

from .config import Settings, load_settings
from .crypto import SecretBox
from .db import Storage
from .handlers import build_router
from .middlewares import AccessMiddleware, SingleFlightMiddleware
from .tts import build_registry
from .watchdog import watch_console

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="voices", description="Голоса: список и переключение"),
    BotCommand(command="addvoice", description="Добавить голос"),
    BotCommand(command="delvoice", description="Удалить голос"),
    BotCommand(command="provider", description="Выбрать TTS-сервис"),
    BotCommand(command="setkey", description="Задать API-ключ"),
    BotCommand(command="delkey", description="Удалить API-ключ"),
    BotCommand(command="format", description="Формат ответа"),
    BotCommand(command="settings", description="Текущие настройки"),
    BotCommand(command="test", description="Проверить настройки"),
    BotCommand(command="help", description="Справка"),
    BotCommand(command="cancel", description="Отменить диалог"),
]


def setup_logging(level: str, log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        # В фоновом режиме (автозапуск, pythonw) консоли нет — пишем в файл.
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
        )

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run(settings: Settings) -> None:
    storage = Storage(settings.db_path, SecretBox(settings.encryption_key))
    await storage.connect()
    registry = build_registry()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["storage"] = storage
    dp["registry"] = registry
    dp["settings"] = settings

    access = AccessMiddleware(settings)
    single_flight = SingleFlightMiddleware()
    for observer in (dp.message, dp.callback_query):
        observer.middleware(access)
        observer.middleware(single_flight)

    dp.include_router(build_router())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Одна упавшая обработка не должна ронять polling.
        log.exception("Необработанная ошибка в хендлере", exc_info=event.exception)
        return True

    # Если запущены из run.bat — гасимся вместе с его окном.
    background: list[asyncio.Task[None]] = []
    if settings.watch_console:
        stop_event = asyncio.Event()
        background.append(asyncio.create_task(watch_console(stop_event)))
        background.append(asyncio.create_task(_stop_on_event(stop_event, dp)))

    try:
        me = await bot.get_me()
        await bot.set_my_commands(COMMANDS)
        log.info(
            "Запущен как @%s. Доступ: %s",
            me.username,
            f"{len(settings.allowed_user_ids)} пользователей"
            if settings.allowed_user_ids
            else "открыт всем",
        )
        # Сбрасываем накопившиеся за время простоя апдейты.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, handle_signals=True)
    except TelegramUnauthorizedError:
        log.error("Telegram отклонил BOT_TOKEN. Проверьте значение в .env")
        raise SystemExit(1) from None
    finally:
        for task in background:
            task.cancel()
        await registry.aclose()
        await storage.close()
        await bot.session.close()
        log.info("Остановлен")


async def _stop_on_event(event: asyncio.Event, dp: Dispatcher) -> None:
    await event.wait()
    try:
        await dp.stop_polling()
    except RuntimeError:
        # Polling уже остановлен — гасимся штатно.
        pass


def main() -> None:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    setup_logging(settings.log_level, settings.log_file)
    try:
        asyncio.run(run(settings))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
