@echo off
rem IMPORTANT: keep this file ASCII-only.
rem cmd.exe parses .bat in the OEM code page, so non-ASCII text inside echo
rem breaks if(...) blocks and fragments get executed as commands.
rem Russian messages are printed by the bot itself: it writes UTF-8,
rem which is why chcp 65001 is set below.
chcp 65001 >nul
title Telegram TTS bot
cd /d "%~dp0"

echo ============================================
echo   Telegram TTS bot
echo   Close this window to stop the bot.
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" goto no_venv
if not exist ".env" goto no_env

rem A second instance on the same token breaks getUpdates (Telegram replies
rem with Conflict), so stop a leftover bot process if there is one.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*bot.main*' } | ForEach-Object { Write-Host ('Stopping previous bot instance, PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

rem Tell the bot to watch this console window. The bot resolves the shell PID
rem itself: if the window is killed hard (Task Manager), it notices and shuts
rem down instead of lingering and polling Telegram forever.
set "WATCH_CONSOLE=1"

".venv\Scripts\python.exe" -m bot.main

echo.
echo Bot stopped.
pause
exit /b 0

:no_venv
echo [ERROR] Virtualenv not found: .venv\Scripts\python.exe
echo.
echo Create it:
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1

:no_env
echo [ERROR] File .env not found.
echo Copy .env.example to .env and fill BOT_TOKEN and ENCRYPTION_KEY.
echo.
pause
exit /b 1
