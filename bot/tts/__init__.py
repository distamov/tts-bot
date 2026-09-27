"""Реестр TTS-провайдеров."""
from __future__ import annotations

import httpx

from .base import CredentialField, TTSError, TTSProvider, TTSRequest
from .fish import FishAudioProvider
from .minimax import MiniMaxProvider

__all__ = [
    "CredentialField",
    "ProviderRegistry",
    "TTSError",
    "TTSProvider",
    "TTSRequest",
    "build_registry",
]

DEFAULT_PROVIDER = "fish"


class ProviderRegistry:
    def __init__(self, providers: dict[str, TTSProvider], client: httpx.AsyncClient) -> None:
        self._providers = providers
        self._client = client

    def get(self, provider_id: str) -> TTSProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise KeyError(f"Неизвестный провайдер: {provider_id}") from None

    def get_or_default(self, provider_id: str | None) -> TTSProvider:
        if provider_id and provider_id in self._providers:
            return self._providers[provider_id]
        return self._providers[DEFAULT_PROVIDER]

    def all(self) -> list[TTSProvider]:
        return list(self._providers.values())

    def ids(self) -> list[str]:
        return list(self._providers)

    async def aclose(self) -> None:
        await self._client.aclose()


def build_registry() -> ProviderRegistry:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=15.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=True,
    )
    providers: dict[str, TTSProvider] = {}
    for cls in (FishAudioProvider, MiniMaxProvider):
        instance = cls(client)
        providers[instance.id] = instance
    return ProviderRegistry(providers, client)
