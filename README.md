# Telegram-бот озвучки текста

Присылаете текст — получаете аудио. Работает через Fish Audio (модель `s2.1-pro-free`),
умеет переключаться на другие TTS-сервисы, хранит несколько именованных голосов
и держит API-ключи в зашифрованном виде.

## Что умеет

| Команда | Что делает |
|---|---|
| *(просто текст)* | озвучивает и присылает аудио |
| *(файл .txt)* | озвучивает содержимое файла (до 200 КБ) |
| `/voices` | список сохранённых голосов, переключение одним нажатием |
| `/addvoice` | добавить голос: имя + voice id (или ссылка `fish.audio/m/<id>`) |
| `/delvoice` | удалить голос |
| `/provider` | переключить TTS-сервис (Fish Audio ⇄ MiniMax ⇄ …) |
| `/setkey` | задать API-ключ активного сервиса |
| `/delkey` | удалить сохранённый ключ |
| `/format` | MP3-файлом, голосовым сообщением (OGG/Opus) или WAV |
| `/settings` | что настроено сейчас + расход символов и оценка стоимости |
| `/test` | проверить связку «ключ + голос» одной фразой |
| `/stats` | статистика по всем пользователям (только для админов) |

Длинный текст режется по предложениям, куски синтезируются по очереди,
MP3-фрагменты склеиваются в один файл.

### Инлайн-теги

Fish Audio понимает теги прямо в тексте:

```
Привет! [pause] У меня для тебя [excited] отличные новости.
```

`[pause]`, `[long pause]`, `[excited]`, `[whisper]`, `[sad]`, `[angry]`, `[laugh]`.
Бот их не трогает — передаёт как есть и не разрывает при нарезке текста.

## Быстрый старт локально

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # Linux/macOS: cp .env.example .env
python scripts/genkey.py        # значение вписать в ENCRYPTION_KEY
```

В `.env` заполнить как минимум:

```env
BOT_TOKEN=<токен от @BotFather>
ENCRYPTION_KEY=<вывод scripts/genkey.py>
ALLOWED_USER_IDS=<ваш Telegram ID>
```

Запуск:

```bash
python -m bot.main
```

Дальше в чате с ботом: `/setkey` → ключ Fish Audio → `/addvoice` → `/test`.

Проверка внутренней логики без Telegram и без обращений к API:

```bash
python scripts/selftest.py
```

## Как хранятся ключи

Три уровня, ни на одном ключ не лежит в коде:

1. **Секреты сервера** (`BOT_TOKEN`, `ENCRYPTION_KEY`) — только в `.env`,
   который в `.gitignore` и в Docker-образ не попадает (`.dockerignore`).
   На сервере ему ставится `chmod 600`.
2. **Ключи пользователей** — в SQLite, зашифрованы Fernet (AES-128-CBC + HMAC).
   Ключ шифрования берётся из `ENCRYPTION_KEY`, то есть дамп базы без
   переменной окружения бесполезен.
3. **В чате** — сообщение с ключом бот удаляет сразу после сохранения,
   а в `/settings` ключ показывается замаскированным (`abcd…wxyz (32 симв.)`).

Если `ENCRYPTION_KEY` потерян, сохранённые ключи не восстановить — их
придётся задать заново через `/setkey`. **Сделайте бэкап `.env`.**

`ALLOWED_USER_IDS` ограничивает круг пользователей: платит-то владелец ключа.
Пустое значение = доступ открыт всем, для публичного бота так делать не стоит.

## Запуск на своём ПК (Windows)

Двойной клик по **`run.bat`** — открывается окно, бот работает.
**Закрыли окно — бот остановился.** Больше ничего настраивать не нужно.

Что делает `run.bat`:

* проверяет, что на месте `.venv` и `.env`, и объясняет, чего не хватает;
* снимает прежний экземпляр бота, если тот остался висеть — иначе Telegram
  отдаёт `Conflict`, и два процесса дерутся за одни и те же обновления;
* запускает бота и держит его, пока открыто окно.

Бот следит за окном сам: находит процесс оболочки вверх по цепочке родителей
и проверяет его раз в 3 секунды. Поэтому он корректно завершается даже если
окно убили жёстко — через диспетчер задач, — а не остаётся сиротой,
продолжая опрашивать Telegram.

Логи видны в самом окне и дублируются в `data/bot.log`
(ротация: 5 МБ, 3 архива) — удобно, когда окно уже закрыли.

Файл `run.bat` должен оставаться в ASCII: `cmd.exe` читает `.bat`
в OEM-кодировке, и кириллица внутри `echo` ломает разбор блоков `if`.
Русские сообщения печатает сам бот — он пишет UTF-8, для этого в начале
стоит `chcp 65001`.

Автозапуск вместе с Windows намеренно не настраивается: бот поднимается
только когда вы сами открыли `run.bat`. Если нужен режим «всегда на связи»,
это задача сервера — см. ниже.

## Деплой

Бот работает на long polling — белый IP, домен и HTTPS не нужны.
Подойдёт любая VPS от 512 МБ RAM.

### Вариант 1. Docker (рекомендуется)

```bash
git clone <репозиторий> tts-bot && cd tts-bot
cp .env.example .env
docker run --rm python:3.12-slim python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
nano .env                 # BOT_TOKEN, ENCRYPTION_KEY, ALLOWED_USER_IDS
chmod 600 .env

docker compose up -d --build
docker compose logs -f
```

База лежит в `./data/bot.db` на хосте — переживает пересборку образа.
`restart: unless-stopped` поднимает бота после перезагрузки сервера.

Обновление:

```bash
git pull && docker compose up -d --build
```

### Вариант 2. systemd, без Docker

```bash
sudo bash deploy/install.sh
sudo nano /opt/tts-bot/.env      # вписать BOT_TOKEN
sudo systemctl start tts-bot
journalctl -u tts-bot -f
```

Скрипт ставит Python, создаёт системного пользователя `ttsbot`, разворачивает
venv в `/opt/tts-bot`, генерирует `ENCRYPTION_KEY` и включает автозапуск.
Юнит запускается с `ProtectSystem=strict` и `NoNewPrivileges`.

### Вариант 3. PaaS (Railway / Fly.io / Amvera)

Dockerfile самодостаточен. Нужно только:

* задать переменные окружения `BOT_TOKEN`, `ENCRYPTION_KEY`, `ALLOWED_USER_IDS`
  через панель провайдера (не через `.env` в репозитории);
* примонтировать постоянный диск на `/app/data` и выставить `DB_PATH=/app/data/bot.db`,
  иначе голоса и ключи будут теряться при каждом редеплое;
* тип сервиса — worker/background, HTTP-порт не нужен.

## Стоимость

Fish Audio берёт **$15 за 1 млн UTF-8 байт**. Кириллица — 2 байта на символ,
то есть **≈ $0.03 за 1000 символов** русского текста (латиница вдвое дешевле).
Бот считает израсходованные байты и показывает оценку в подписи к аудио и в `/settings`.

Модель `s2.1-pro-free` бесплатна и по качеству совпадает с платной `s2.1-pro`,
но у неё жёсткий rate limit и нет SLA. При 429 бот делает три попытки
с нарастающей паузой и потом сообщает, что лимит исчерпан.

## Как добавить свой TTS-сервис

1. Создайте `bot/tts/<сервис>.py` с классом-наследником `TTSProvider`:

```python
class MyProvider(TTSProvider):
    id = "myservice"
    title = "My Service"
    formats = ("mp3",)
    usd_per_million_bytes = None          # или цена за 1 млн UTF-8 байт
    credential_fields = (
        CredentialField(key="api_key", title="API-ключ"),
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def synthesize(self, req: TTSRequest, creds: dict) -> bytes:
        ...   # вернуть аудиобайты, ошибки бросать как TTSError
```

2. Добавьте класс в кортеж в `build_registry()` в `bot/tts/__init__.py`.

Всё остальное — команда `/provider`, диалог `/setkey` под нужные поля,
голоса и учёт расхода — подхватится само.

## Структура

```
bot/
  main.py           запуск, диспетчер, регистрация команд
  config.py         чтение .env
  crypto.py         шифрование ключей (Fernet)
  db.py             SQLite: пользователи, ключи, голоса, учёт расхода
  middlewares.py    контроль доступа, защита от параллельных запросов
  keyboards.py      инлайн-клавиатуры
  utils.py          нарезка текста, форматирование
  watchdog.py       слежение за окном консоли (остановка вместе с run.bat)
  tts/
    base.py         интерфейс провайдера
    fish.py         Fish Audio
    minimax.py      MiniMax
  handlers/
    common.py       /start /help /settings /cancel /stats
    keys.py         /provider /setkey /delkey /format
    voices.py       /voices /addvoice /delvoice
    tts.py          текст → аудио
run.bat             запуск на Windows: открыл - работает, закрыл - остановился
deploy/             systemd-юнит и install.sh
scripts/            genkey.py, selftest.py
```

## Известные ограничения

* Голосовые сообщения (`/format` → OGG/Opus) отдаёт сам Fish Audio;
  ffmpeg не используется, конвертации нет. Если сервис откажет в этом формате,
  переключитесь на MP3.
* Склейка нескольких фрагментов работает только для MP3. Для OGG/WAV длинный
  текст придёт несколькими сообщениями.
* Учёт расхода — оценка по объёму отправленного текста, а не биллинг провайдера.
  Точные суммы смотрите в личном кабинете Fish Audio.
