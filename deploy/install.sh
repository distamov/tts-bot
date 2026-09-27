#!/usr/bin/env bash
# Установка бота на чистый Ubuntu/Debian VPS без Docker.
# Запускать от root: bash deploy/install.sh
set -euo pipefail

APP_DIR=/opt/tts-bot
APP_USER=ttsbot

echo "==> Пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync

echo "==> Пользователь ${APP_USER}"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

echo "==> Код в ${APP_DIR}"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.venv' --exclude 'data' --exclude '.env' --exclude '__pycache__' \
  "$(cd "$(dirname "$0")/.." && pwd)/" "$APP_DIR/"
mkdir -p "$APP_DIR/data"

echo "==> Виртуальное окружение"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "==> .env"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  KEY="$("$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/genkey.py")"
  sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${KEY}|" "$APP_DIR/.env"
  echo "    Сгенерирован ENCRYPTION_KEY. Впишите BOT_TOKEN в $APP_DIR/.env"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 700 "$APP_DIR/data"

echo "==> systemd"
cp "$APP_DIR/deploy/tts-bot.service" /etc/systemd/system/tts-bot.service
systemctl daemon-reload
systemctl enable tts-bot

cat <<EOF

Готово. Осталось:
  1) nano ${APP_DIR}/.env   — вписать BOT_TOKEN (и, если нужно, ALLOWED_USER_IDS)
  2) systemctl start tts-bot
  3) journalctl -u tts-bot -f   — смотреть логи
EOF
