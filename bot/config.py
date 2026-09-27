"""Конфигурация из переменных окружения (.env не коммитится)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.add(int(part))
            except ValueError:
                raise RuntimeError(f"Некорректный user id в конфиге: {part!r}")
    return out


@dataclass(frozen=True)
class Settings:
    bot_token: str
    encryption_key: str
    allowed_user_ids: set[int] = field(default_factory=set)
    admin_user_ids: set[int] = field(default_factory=set)
    default_fish_api_key: str = ""
    default_fish_model: str = "s2.1-pro-free"
    default_fish_voice_id: str = ""
    db_path: Path = BASE_DIR / "data" / "bot.db"
    log_level: str = "INFO"
    log_file: Path | None = None
    watch_console: bool = False
    max_text_chars: int = 8000

    def is_allowed(self, user_id: int) -> bool:
        # Пустой список = открытый доступ.
        return not self.allowed_user_ids or user_id in self.allowed_user_ids

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_user_ids


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")

    enc = os.getenv("ENCRYPTION_KEY", "").strip()
    if not enc:
        raise RuntimeError(
            "ENCRYPTION_KEY не задан. Сгенерируйте: python scripts/genkey.py "
            "и добавьте значение в .env"
        )

    db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    log_file: Path | None = None
    raw_log_file = os.getenv("LOG_FILE", "").strip()
    if raw_log_file:
        log_file = Path(raw_log_file)
        if not log_file.is_absolute():
            log_file = BASE_DIR / log_file

    return Settings(
        bot_token=token,
        encryption_key=enc,
        allowed_user_ids=_ids(os.getenv("ALLOWED_USER_IDS")),
        admin_user_ids=_ids(os.getenv("ADMIN_USER_IDS")),
        default_fish_api_key=os.getenv("DEFAULT_FISH_API_KEY", "").strip(),
        default_fish_model=os.getenv("DEFAULT_FISH_MODEL", "s2.1-pro-free").strip(),
        default_fish_voice_id=os.getenv("DEFAULT_FISH_VOICE_ID", "").strip(),
        db_path=db_path,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=log_file,
        # Выставляется скриптом запуска (run.bat), а не пользователем.
        watch_console=os.getenv("WATCH_CONSOLE", "").strip() in ("1", "true", "yes"),
        max_text_chars=int(os.getenv("MAX_TEXT_CHARS", "8000")),
    )
