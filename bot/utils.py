"""Вспомогательные функции: нарезка текста, форматирование."""
from __future__ import annotations

import re

# Инлайн-теги Fish Audio: [pause], [excited], [whisper] и т.п.
TAG_RE = re.compile(r"\[[a-zA-Z_][a-zA-Z0-9_ -]{0,30}\]")

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…])$")


def split_text(text: str, max_chars: int) -> list[str]:
    """Нарезать текст на куски <= max_chars, не разрывая теги и по возможности предложения."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    for block in _split_paragraphs(text, max_chars):
        chunks.extend(_split_block(block, max_chars))
    return [c for c in (c.strip() for c in chunks) if c]


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    merged: list[str] = []
    buf = ""
    for para in paragraphs:
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)
    return merged


def _split_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]

    pieces = [p for p in _SENTENCE_END.split(block) if p and p.strip()]
    out: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            out.append(buf)
            buf = ""
        if len(piece) <= max_chars:
            buf = piece
        else:
            out.extend(_hard_split(piece, max_chars))
    if buf:
        out.append(buf)
    return out


def _hard_split(piece: str, max_chars: int) -> list[str]:
    """Последний рубеж: режем по словам, не разрывая теги вида [pause]."""
    out: list[str] = []
    buf = ""
    for token in re.split(r"(\s+)", piece):
        if not token:
            continue
        if len(buf) + len(token) <= max_chars:
            buf += token
            continue
        if buf.strip():
            out.append(buf.strip())
        buf = ""
        while len(token) > max_chars:
            # Одно слово длиннее лимита — режем как есть.
            out.append(token[:max_chars])
            token = token[max_chars:]
        buf = token
    if buf.strip():
        out.append(buf.strip())
    return out


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def found_tags(text: str) -> list[str]:
    return sorted({m.group(0) for m in TAG_RE.finditer(text)})


def utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def format_cost(usd: float | None) -> str:
    # Без символа "<": строка уходит в подпись с parse_mode=HTML,
    # и Telegram принял бы его за начало тега.
    if usd is None:
        return "—"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"


def audio_extension(fmt: str) -> str:
    return {"mp3": "mp3", "opus": "ogg", "wav": "wav"}.get(fmt, "mp3")


def audio_mime(fmt: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "wav": "audio/wav",
    }.get(fmt, "audio/mpeg")


def safe_filename(text: str, ext: str, limit: int = 32) -> str:
    base = strip_tags(text).strip()
    base = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE).strip()
    base = re.sub(r"\s+", "_", base)[:limit]
    return f"{base or 'voice'}.{ext}"
