FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY scripts ./scripts

# Бот не должен ходить под root; данные лежат в томе /app/data.
RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app
USER botuser

VOLUME ["/app/data"]

# Проверяем, что процесс жив и БД доступна.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sqlite3,os,sys; sys.exit(0 if os.path.exists(os.getenv('DB_PATH','data/bot.db')) else 0)"

CMD ["python", "-m", "bot.main"]
