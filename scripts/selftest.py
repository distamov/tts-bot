"""Проверка внутренней логики без обращения к Telegram и TTS-сервисам.

Запуск: python scripts/selftest.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet  # noqa: E402

from bot.crypto import SecretBox, mask  # noqa: E402
from bot.db import Storage  # noqa: E402
from bot.tts import build_registry  # noqa: E402
from bot.utils import format_cost, split_text, utf8_bytes  # noqa: E402
from bot.watchdog import _snapshot, pid_alive  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))


async def main() -> int:
    # --- шифрование ---
    box = SecretBox(Fernet.generate_key().decode())
    blob = box.encrypt({"api_key": "secret-key-123", "model": "s2.1-pro-free"})
    restored = box.decrypt(blob)
    check("шифрование/расшифровка ключей", restored["api_key"] == "secret-key-123")
    check("ключ не лежит в БД открытым текстом", b"secret-key-123" not in blob)
    check("маскирование ключа", "secret-key-123" not in mask("secret-key-123"))

    wrong = SecretBox(Fernet.generate_key().decode())
    try:
        wrong.decrypt(blob)
        check("чужой ключ не расшифровывает", False, "расшифровал — это баг")
    except RuntimeError:
        check("чужой ключ не расшифровывает", True)

    # --- хранилище ---
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp) / "test.db", box)
        await storage.connect()

        state = await storage.get_user(42)
        check("новый пользователь создаётся", state.active_provider == "fish")

        await storage.set_credentials(42, "fish", {"api_key": "abc123456", "model": "s1"})
        creds = await storage.get_credentials(42, "fish")
        check("ключи сохраняются и читаются", creds == {"api_key": "abc123456", "model": "s1"})
        check("список настроенных провайдеров", await storage.providers_with_credentials(42) == {"fish"})

        v1 = await storage.add_voice(42, "fish", "Диктор", "abc123")
        v2 = await storage.add_voice(42, "fish", "Мягкий", "def456")
        check("голоса сохраняются", len(await storage.list_voices(42, "fish")) == 2)

        await storage.add_voice(42, "fish", "Диктор", "zzz999")
        again = await storage.get_voice_by_name(42, "fish", "Диктор")
        check("повторное имя обновляет id голоса", again is not None and again.voice_ref == "zzz999")
        check("дубликат не создаёт запись", len(await storage.list_voices(42, "fish")) == 2)

        await storage.update_user(42, active_voice_id=v2.id)
        check("активный голос переключается", (await storage.get_user(42)).active_voice_id == v2.id)

        await storage.delete_voice(42, v2.id)
        check("удаление голоса сбрасывает активный", (await storage.get_user(42)).active_voice_id is None)

        check("чужой голос не виден", not await storage.list_voices(999, "fish"))

        await storage.log_usage(42, "fish", 100, 180, ok=True)
        await storage.log_usage(42, "fish", 50, 90, ok=False)
        totals = await storage.usage_totals(42)
        check("учёт расхода считает только успешные", totals == {"requests": 1, "chars": 100, "utf8_bytes": 180})

        check("удаление ключа", await storage.delete_credentials(42, "fish"))
        check("ключа больше нет", await storage.get_credentials(42, "fish") is None)
        _ = v1
        await storage.close()

    # --- нарезка текста ---
    long_text = ("Это предложение номер один. Это предложение номер два! " * 80).strip()
    chunks = split_text(long_text, 300)
    check("нарезка укладывается в лимит", all(len(c) <= 300 for c in chunks), f"max={max(map(len, chunks))}")
    check("нарезка ничего не теряет", "".join(chunks).replace(" ", "") == long_text.replace(" ", ""))
    check("короткий текст не режется", split_text("Привет", 300) == ["Привет"])
    check("пустой текст даёт пустой список", split_text("   ", 300) == [])

    tagged = "Привет! [pause] У меня [excited] отличные новости для тебя сегодня."
    tag_chunks = split_text(tagged, 30)
    check("теги не разрываются", all("[" not in c or "]" in c for c in tag_chunks), str(tag_chunks))

    word = "а" * 700
    check("сверхдлинное слово режется", all(len(c) <= 200 for c in split_text(word, 200)))

    # --- стоимость ---
    registry = build_registry()
    fish = registry.get("fish")
    text_1000 = "п" * 1000
    check("кириллица = 2 байта на символ", utf8_bytes(text_1000) == 2000)
    cost = fish.estimate_cost_usd(text_1000)
    check("оценка ~$0.03 за 1000 кириллических символов", abs(cost - 0.03) < 1e-9, f"{cost}")
    check("latin дешевле вдвое", abs(fish.estimate_cost_usd("a" * 1000) - 0.015) < 1e-9)

    # Подпись уходит с parse_mode=HTML: символы <, >, & ломают отправку целиком.
    samples = [format_cost(None), format_cost(0.0), format_cost(0.0004), format_cost(1.5)]
    check(
        "стоимость не ломает HTML-разметку подписи",
        all(not set(s) & set("<>&") for s in samples),
        str(samples),
    )
    await registry.aclose()

    # --- слежение за окном консоли ---
    check("свой процесс определяется живым", pid_alive(os.getpid()))
    check("несуществующий PID определяется мёртвым", not pid_alive(999_999))
    check("PID 0 не считается живым", not pid_alive(0))
    check("отрицательный PID не считается живым", not pid_alive(-1))
    if os.name == "nt":
        snap = _snapshot()
        check("снимок процессов Windows читается", len(snap) > 10, f"получено {len(snap)}")
        check(
            "текущий процесс есть в снимке",
            os.getpid() in snap,
            "цепочка родителей не построится",
        )

    # --- вывод ---
    failed = 0
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        suffix = f"  <- {detail}" if detail and not ok else ""
        print(f"[{mark}] {name}{suffix}")
        failed += not ok

    print(f"\n{len(checks) - failed}/{len(checks)} проверок пройдено")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
