"""Fish Audio TTS (https://fish.audio)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import CredentialField, TTSError, TTSProvider, TTSRequest

log = logging.getLogger(__name__)

API_URL = "https://api.fish.audio/v1/tts"

# s2.1-pro-free — бесплатная, по качеству равна платной s2.1-pro,
# но с rate limit и без SLA.
KNOWN_MODELS = ("s2.1-pro-free", "s2.1-pro", "s1", "s1-mini", "speech-1.6")


class FishAudioProvider(TTSProvider):
    id = "fish"
    title = "Fish Audio"
    signup_url = "https://fish.audio/go-api/"
    formats = ("mp3", "opus", "wav")
    # $15 за 1 млн UTF-8 байт. Кириллица = 2 байта/символ,
    # то есть примерно $0.03 за 1000 символов.
    usd_per_million_bytes = 15.0
    max_chunk_chars = 1500
    supports_inline_tags = True

    credential_fields = (
        CredentialField(
            key="api_key",
            title="API-ключ",
            hint="Ключ вида xxxxxxxx… со страницы fish.audio → API Keys",
        ),
        CredentialField(
            key="model",
            title="Модель",
            hint=f"Например: {', '.join(KNOWN_MODELS[:3])}",
            secret=False,
            required=False,
            default="s2.1-pro-free",
        ),
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def synthesize(self, req: TTSRequest, creds: dict[str, Any]) -> bytes:
        api_key = str(creds.get("api_key", "")).strip()
        if not api_key:
            raise TTSError("Не задан API-ключ Fish Audio. Задайте его командой /setkey.")

        model = str(creds.get("model") or "s2.1-pro-free").strip()
        fmt = req.fmt if req.fmt in self.formats else "mp3"

        payload: dict[str, Any] = {
            "text": req.text,
            "format": fmt,
            "normalize": True,
            "latency": "normal",
        }
        if fmt == "mp3":
            payload["mp3_bitrate"] = int(req.extra.get("mp3_bitrate", 128))
        if req.voice_ref:
            payload["reference_id"] = req.voice_ref

        headers = {
            "Authorization": f"Bearer {api_key}",
            "model": model,
            "Content-Type": "application/json",
        }

        last_error: TTSError | None = None
        for attempt in range(3):
            try:
                resp = await self._client.post(API_URL, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = TTSError("Fish Audio не ответил вовремя.", retryable=True)
                log.warning("fish timeout (попытка %s): %s", attempt + 1, exc)
            except httpx.HTTPError as exc:
                last_error = TTSError(f"Сеть недоступна: {exc}", retryable=True)
                log.warning("fish network error (попытка %s): %s", attempt + 1, exc)
            else:
                if resp.status_code == 200:
                    audio = resp.content
                    if not audio:
                        raise TTSError("Fish Audio вернул пустой ответ.")
                    return audio
                last_error = _http_error(resp, model)
                if not last_error.retryable:
                    raise last_error
                log.warning("fish %s (попытка %s)", resp.status_code, attempt + 1)

            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

        raise last_error or TTSError("Fish Audio недоступен.")


def _http_error(resp: httpx.Response, model: str) -> TTSError:
    detail = ""
    try:
        body = resp.json()
        detail = str(body.get("detail") or body.get("message") or body)[:300]
    except Exception:  # noqa: BLE001 — тело может быть не JSON
        detail = resp.text[:300]

    code = resp.status_code
    if code in (401, 403):
        return TTSError(
            "Fish Audio отклонил ключ (401/403). Проверьте его через /setkey.\n"
            f"Ответ сервиса: {detail}"
        )
    if code == 402:
        return TTSError(f"На счету Fish Audio недостаточно средств.\n{detail}")
    if code == 404:
        return TTSError(
            "Fish Audio не нашёл голос или модель. Проверьте reference_id "
            f"голоса и название модели ({model}).\n{detail}"
        )
    if code == 422:
        return TTSError(f"Fish Audio не принял запрос: {detail}")
    if code == 429:
        return TTSError(
            "Лимит запросов Fish Audio исчерпан — у бесплатной модели он жёсткий. "
            "Подождите немного и повторите.",
            retryable=True,
        )
    if code >= 500:
        return TTSError(f"Ошибка на стороне Fish Audio ({code}).", retryable=True)
    return TTSError(f"Fish Audio вернул {code}: {detail}")
