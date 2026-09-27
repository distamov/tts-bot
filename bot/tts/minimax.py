"""MiniMax T2A v2 (https://www.minimax.io) — пример второго провайдера."""
from __future__ import annotations

import binascii
import logging
from typing import Any

import httpx

from .base import CredentialField, TTSError, TTSProvider, TTSRequest

log = logging.getLogger(__name__)

API_URL = "https://api.minimax.io/v1/t2a_v2"


class MiniMaxProvider(TTSProvider):
    id = "minimax"
    title = "MiniMax"
    signup_url = "https://www.minimax.io/platform"
    formats = ("mp3",)
    usd_per_million_bytes = None  # тарификация у MiniMax посимвольная и зависит от модели
    max_chunk_chars = 1500
    supports_inline_tags = False

    credential_fields = (
        CredentialField(key="api_key", title="API-ключ", hint="Bearer-токен из личного кабинета"),
        CredentialField(key="group_id", title="GroupId", hint="GroupId из личного кабинета"),
        CredentialField(
            key="model",
            title="Модель",
            hint="Например: speech-02-hd",
            secret=False,
            required=False,
            default="speech-02-hd",
        ),
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def synthesize(self, req: TTSRequest, creds: dict[str, Any]) -> bytes:
        api_key = str(creds.get("api_key", "")).strip()
        group_id = str(creds.get("group_id", "")).strip()
        if not api_key or not group_id:
            raise TTSError("Для MiniMax нужны API-ключ и GroupId. Задайте их через /setkey.")

        model = str(creds.get("model") or "speech-02-hd").strip()
        payload: dict[str, Any] = {
            "model": model,
            "text": req.text,
            "stream": False,
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }
        if req.voice_ref:
            payload["voice_setting"] = {
                "voice_id": req.voice_ref,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            }

        try:
            resp = await self._client.post(
                API_URL,
                params={"GroupId": group_id},
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            raise TTSError("MiniMax не ответил вовремя.", retryable=True) from None
        except httpx.HTTPError as exc:
            raise TTSError(f"Сеть недоступна: {exc}", retryable=True) from None

        if resp.status_code != 200:
            raise TTSError(f"MiniMax вернул {resp.status_code}: {resp.text[:300]}")

        try:
            body = resp.json()
        except ValueError:
            raise TTSError("MiniMax вернул не-JSON ответ.") from None

        base_resp = body.get("base_resp") or {}
        status_code = base_resp.get("status_code", 0)
        if status_code not in (0, None):
            raise TTSError(
                f"MiniMax: {base_resp.get('status_msg', 'ошибка')} (код {status_code})"
            )

        hex_audio = (body.get("data") or {}).get("audio")
        if not hex_audio:
            raise TTSError("MiniMax не вернул аудио.")
        try:
            return binascii.unhexlify(hex_audio)
        except binascii.Error as exc:
            raise TTSError(f"Не удалось разобрать аудио от MiniMax: {exc}") from exc
