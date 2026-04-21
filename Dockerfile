FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot/ ./bot/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

RUN chown -R pwuser:pwuser /app
USER pwuser

ENV PYTHONUNBUFFERED=1 \
    FASTAPI_HOST=0.0.0.0 \
    FASTAPI_PORT=8765 \
    BOT_DB_PATH=/app/data/bot.sqlite3 \
    PLAYWRIGHT_PROFILES_DIR=/app/data/profiles \
    ATTACHMENT_TMP_DIR=/app/data/tmp

EXPOSE 8765

CMD ["python", "-m", "bot.main"]
