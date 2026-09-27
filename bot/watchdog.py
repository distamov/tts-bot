"""Слежение за окном консоли, из которого запущен бот.

run.bat выставляет WATCH_CONSOLE=1. Бот сам находит вверх по цепочке
родителей процесс оболочки (cmd/powershell) и следит за ним: закрыли окно —
бот завершается, а не остаётся висеть сиротой и опрашивать Telegram.

Вычислять PID в самом .bat нельзя: `for /f` запускает команду через
промежуточный cmd.exe, и её родителем оказывается этот временный процесс.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger(__name__)

_POLL_SECONDS = 3.0
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002
_MAX_PATH = 260
_MAX_DEPTH = 12

#: Процессы, которые считаем «окном», из которого запустили бота.
SHELL_NAMES = frozenset({"cmd.exe", "powershell.exe", "pwsh.exe"})


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * _MAX_PATH),
    ]


def _snapshot() -> dict[int, tuple[int, str]]:
    """pid -> (ppid, имя exe). Пустой словарь, если снять снимок не удалось."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if handle == -1:
        return {}

    result: dict[int, tuple[int, str]] = {}
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        if not kernel32.Process32First(handle, ctypes.byref(entry)):
            return {}
        while True:
            name = entry.szExeFile.decode("latin-1", errors="replace").lower()
            result[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), name)
            if not kernel32.Process32Next(handle, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(handle)
    return result


def find_console_ancestor() -> int:
    """PID ближайшей оболочки-предка. 0, если такой нет."""
    if os.name != "nt":
        return 0

    processes = _snapshot()
    if not processes:
        return 0

    pid = os.getpid()
    for _ in range(_MAX_DEPTH):
        entry = processes.get(pid)
        if entry is None:
            return 0
        parent_pid, _name = entry
        parent = processes.get(parent_pid)
        if parent is None:
            return 0
        if parent[1] in SHELL_NAMES:
            return parent_pid
        pid = parent_pid
    return 0


def pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким PID."""
    if pid <= 0:
        return False

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Процесс есть, просто чужой.
            return True
        return True

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


async def watch_console(on_exit: asyncio.Event) -> None:
    """Ставить on_exit, когда закроется окно, из которого запустили бота."""
    pid = find_console_ancestor()
    if not pid:
        log.warning("Окно-родитель не найдено — слежение за закрытием отключено")
        return

    log.info("Слежу за окном консоли (PID %s): закроют — остановлюсь", pid)
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        if not pid_alive(pid):
            log.info("Окно консоли (PID %s) закрыто — останавливаюсь", pid)
            on_exit.set()
            return
