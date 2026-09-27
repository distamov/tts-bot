"""Сборка роутеров. Порядок важен: tts ловит любой текст и должен идти последним."""
from __future__ import annotations

from aiogram import Router

from . import common, keys, tts, voices


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)
    root.include_router(keys.router)
    root.include_router(voices.router)
    root.include_router(tts.router)
    return root
