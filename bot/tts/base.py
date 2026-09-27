"""Общий интерфейс TTS-провайдера.

Чтобы добавить новый сервис, достаточно унаследоваться от TTSProvider
и зарегистрировать класс в bot/tts/__init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class TTSError(Exception):
    """Ошибка синтеза, текст которой можно показать пользователю."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class CredentialField:
    """Одно поле, которое бот спросит у пользователя при /setkey."""

    key: str
    title: str
    hint: str = ""
    secret: bool = True
    required: bool = True
    default: str = ""


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_ref: str | None = None
    fmt: str = "mp3"
    extra: dict[str, Any] = field(default_factory=dict)


class TTSProvider(ABC):
    #: короткий идентификатор, он же ключ в БД
    id: str = ""
    #: человекочитаемое название
    title: str = ""
    #: где взять ключ
    signup_url: str = ""
    #: какие поля спрашивать при /setkey
    credential_fields: tuple[CredentialField, ...] = ()
    #: форматы, которые провайдер умеет отдавать
    formats: tuple[str, ...] = ("mp3",)
    #: цена за миллион UTF-8 байт, USD; None — если неизвестна/бесплатно
    usd_per_million_bytes: float | None = None
    #: сколько символов отправлять в одном запросе
    max_chunk_chars: int = 1500
    #: поддерживает ли инлайн-теги вида [pause], [excited]
    supports_inline_tags: bool = False

    @abstractmethod
    async def synthesize(self, req: TTSRequest, creds: dict[str, Any]) -> bytes:
        """Вернуть готовые аудиобайты в формате req.fmt."""

    def validate_credentials(self, creds: dict[str, Any]) -> None:
        """Бросить TTSError, если обязательных полей не хватает."""
        missing = [
            f.title for f in self.credential_fields if f.required and not str(creds.get(f.key, "")).strip()
        ]
        if missing:
            raise TTSError("Не заполнено: " + ", ".join(missing))

    def estimate_cost_usd(self, text: str) -> float | None:
        if self.usd_per_million_bytes is None:
            return None
        return len(text.encode("utf-8")) / 1_000_000 * self.usd_per_million_bytes

    def describe_credentials(self, creds: dict[str, Any]) -> str:
        """Строка для /settings — секреты замаскированы."""
        from ..crypto import mask

        parts = []
        for f in self.credential_fields:
            value = str(creds.get(f.key, "") or "")
            if not value:
                continue
            parts.append(f"{f.title}: {mask(value) if f.secret else value}")
        return "\n".join(parts) or "— не задано —"
