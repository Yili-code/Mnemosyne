from __future__ import annotations

import hmac
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException, Request

from vocab_bot.config import Settings
from vocab_bot.gemini import GeminiClient
from vocab_bot.repository import FirestoreRepository, Repository, SQLiteRepository
from vocab_bot.service import VocabularyService
from vocab_bot.telegram import TelegramClient

app = FastAPI(title="Mnemosyne", docs_url=None, redoc_url=None)


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_service() -> VocabularyService:
    settings = get_settings()
    repository: Repository
    if settings.storage_backend == "firestore":
        repository = FirestoreRepository(settings.google_cloud_project)
    else:
        repository = SQLiteRepository(settings.sqlite_path)
    return VocabularyService(
        repository=repository,
        gemini=GeminiClient(settings.gemini_api_key, settings.gemini_model),
        telegram=TelegramClient(settings.telegram_bot_token),
        owner_chat_id=settings.telegram_owner_chat_id,
        review_size=settings.review_size,
        timezone=settings.timezone,
    )


def _matches(actual: str | None, expected: str) -> bool:
    return actual is not None and hmac.compare_digest(actual, expected)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    settings = get_settings()
    if not _matches(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    update = await request.json()
    get_service().handle_update(update)
    return {"ok": True}


@app.post("/tasks/daily-review")
def daily_review(x_cron_secret: str | None = Header(default=None)) -> dict[str, object]:
    settings = get_settings()
    if not _matches(x_cron_secret, settings.cron_secret):
        raise HTTPException(status_code=401, detail="Invalid cron secret")
    words = get_service().send_review()
    return {"ok": True, "words": words}


@app.post("/tasks/retry-failed")
def retry_failed(x_cron_secret: str | None = Header(default=None)) -> dict[str, object]:
    settings = get_settings()
    if not _matches(x_cron_secret, settings.cron_secret):
        raise HTTPException(status_code=401, detail="Invalid cron secret")
    result = get_service().retry_failed_word()
    return {"ok": True, **result}
