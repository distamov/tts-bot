"""Хранилище: SQLite через aiosqlite. Секреты лежат зашифрованными."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from .crypto import SecretBox

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    active_provider TEXT    NOT NULL DEFAULT 'fish',
    active_voice_id INTEGER,
    audio_format    TEXT    NOT NULL DEFAULT 'mp3',
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (
    user_id    INTEGER NOT NULL,
    provider   TEXT    NOT NULL,
    secret     BLOB    NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, provider)
);

CREATE TABLE IF NOT EXISTS voices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    provider   TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    voice_ref  TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (user_id, provider, name)
);

CREATE TABLE IF NOT EXISTS usage_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    provider   TEXT    NOT NULL,
    chars      INTEGER NOT NULL,
    utf8_bytes INTEGER NOT NULL,
    ok         INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_voices_user ON voices(user_id, provider);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_log(user_id, created_at);
"""


@dataclass
class Voice:
    id: int
    user_id: int
    provider: str
    name: str
    voice_ref: str


@dataclass
class UserState:
    user_id: int
    active_provider: str
    active_voice_id: int | None
    audio_format: str


def _now() -> int:
    return int(time.time())


class Storage:
    def __init__(self, path: Path, box: SecretBox) -> None:
        self._path = path
        self._box = box
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage.connect() не был вызван")
        return self._db

    # ---------- users ----------

    async def get_user(self, user_id: int) -> UserState:
        cur = await self.db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            now = _now()
            await self.db.execute(
                "INSERT INTO users (user_id, created_at, updated_at) VALUES (?, ?, ?)",
                (user_id, now, now),
            )
            await self.db.commit()
            return UserState(user_id, "fish", None, "mp3")
        return UserState(
            user_id=row["user_id"],
            active_provider=row["active_provider"],
            active_voice_id=row["active_voice_id"],
            audio_format=row["audio_format"],
        )

    async def update_user(self, user_id: int, **fields: Any) -> None:
        allowed = {"active_provider", "active_voice_id", "audio_format"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Нельзя менять поля: {bad}")
        await self.get_user(user_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [_now(), user_id]
        await self.db.execute(
            f"UPDATE users SET {sets}, updated_at = ? WHERE user_id = ?", params
        )
        await self.db.commit()

    async def count_users(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS n FROM users")
        row = await cur.fetchone()
        return int(row["n"])

    # ---------- credentials ----------

    async def set_credentials(self, user_id: int, provider: str, creds: dict[str, Any]) -> None:
        await self.get_user(user_id)
        blob = self._box.encrypt(creds)
        await self.db.execute(
            "INSERT INTO credentials (user_id, provider, secret, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, provider) DO UPDATE SET "
            "secret = excluded.secret, updated_at = excluded.updated_at",
            (user_id, provider, blob, _now()),
        )
        await self.db.commit()

    async def get_credentials(self, user_id: int, provider: str) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT secret FROM credentials WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._box.decrypt(row["secret"])

    async def delete_credentials(self, user_id: int, provider: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM credentials WHERE user_id = ? AND provider = ?", (user_id, provider)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def providers_with_credentials(self, user_id: int) -> set[str]:
        cur = await self.db.execute(
            "SELECT provider FROM credentials WHERE user_id = ?", (user_id,)
        )
        return {r["provider"] for r in await cur.fetchall()}

    # ---------- voices ----------

    async def add_voice(self, user_id: int, provider: str, name: str, voice_ref: str) -> Voice:
        await self.get_user(user_id)
        await self.db.execute(
            "INSERT INTO voices (user_id, provider, name, voice_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, provider, name) DO UPDATE SET voice_ref = excluded.voice_ref",
            (user_id, provider, name, voice_ref, _now()),
        )
        await self.db.commit()
        voice = await self.get_voice_by_name(user_id, provider, name)
        assert voice is not None
        return voice

    async def get_voice(self, voice_id: int) -> Voice | None:
        cur = await self.db.execute("SELECT * FROM voices WHERE id = ?", (voice_id,))
        row = await cur.fetchone()
        return _voice(row) if row else None

    async def get_voice_by_name(self, user_id: int, provider: str, name: str) -> Voice | None:
        cur = await self.db.execute(
            "SELECT * FROM voices WHERE user_id = ? AND provider = ? AND name = ?",
            (user_id, provider, name),
        )
        row = await cur.fetchone()
        return _voice(row) if row else None

    async def list_voices(self, user_id: int, provider: str | None = None) -> list[Voice]:
        if provider:
            cur = await self.db.execute(
                "SELECT * FROM voices WHERE user_id = ? AND provider = ? ORDER BY name",
                (user_id, provider),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM voices WHERE user_id = ? ORDER BY provider, name", (user_id,)
            )
        return [_voice(r) for r in await cur.fetchall()]

    async def delete_voice(self, user_id: int, voice_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM voices WHERE id = ? AND user_id = ?", (voice_id, user_id)
        )
        await self.db.commit()
        if cur.rowcount:
            await self.db.execute(
                "UPDATE users SET active_voice_id = NULL "
                "WHERE user_id = ? AND active_voice_id = ?",
                (user_id, voice_id),
            )
            await self.db.commit()
        return cur.rowcount > 0

    # ---------- usage ----------

    async def log_usage(
        self, user_id: int, provider: str, chars: int, utf8_bytes: int, ok: bool
    ) -> None:
        await self.db.execute(
            "INSERT INTO usage_log (user_id, provider, chars, utf8_bytes, ok, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, provider, chars, utf8_bytes, int(ok), _now()),
        )
        await self.db.commit()

    async def usage_totals(self, user_id: int | None = None) -> dict[str, int]:
        sql = (
            "SELECT COUNT(*) AS requests, COALESCE(SUM(chars), 0) AS chars, "
            "COALESCE(SUM(utf8_bytes), 0) AS utf8_bytes FROM usage_log WHERE ok = 1"
        )
        params: tuple[Any, ...] = ()
        if user_id is not None:
            sql += " AND user_id = ?"
            params = (user_id,)
        cur = await self.db.execute(sql, params)
        row = await cur.fetchone()
        return {
            "requests": int(row["requests"]),
            "chars": int(row["chars"]),
            "utf8_bytes": int(row["utf8_bytes"]),
        }


def _voice(row: aiosqlite.Row) -> Voice:
    return Voice(
        id=row["id"],
        user_id=row["user_id"],
        provider=row["provider"],
        name=row["name"],
        voice_ref=row["voice_ref"],
    )
