"""Симметричное шифрование пользовательских API-ключей.

Ключ шифрования живёт только в переменной окружения ENCRYPTION_KEY.
В БД попадает шифротекст, в коде — ничего.
"""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, key: str) -> None:
        try:
            self._f = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "ENCRYPTION_KEY невалиден. Нужен ключ Fernet (44 символа base64). "
                "Сгенерируйте: python scripts/genkey.py"
            ) from exc

    def encrypt(self, data: dict[str, Any]) -> bytes:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._f.encrypt(raw)

    def decrypt(self, blob: bytes) -> dict[str, Any]:
        try:
            raw = self._f.decrypt(blob)
        except InvalidToken as exc:
            raise RuntimeError(
                "Не удалось расшифровать сохранённые ключи: ENCRYPTION_KEY изменился. "
                "Верните прежний ключ или попросите пользователей заново задать /setkey."
            ) from exc
        return json.loads(raw.decode("utf-8"))


def mask(secret: str) -> str:
    """Показать ключ так, чтобы его можно было опознать, но не использовать."""
    secret = (secret or "").strip()
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}…{secret[-4:]} ({len(secret)} симв.)"
