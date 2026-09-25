from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_owner_chat_id: int
    telegram_webhook_secret: str
    gemini_api_key: str
    gemini_model: str
    cron_secret: str
    storage_backend: str
    sqlite_path: Path
    google_cloud_project: str | None
    review_size: int
    timezone: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        backend = os.getenv("STORAGE_BACKEND", "sqlite").strip().lower()
        if backend not in {"sqlite", "firestore"}:
            raise RuntimeError("STORAGE_BACKEND must be 'sqlite' or 'firestore'")
        review_size = int(os.getenv("REVIEW_SIZE", "20"))
        if not 1 <= review_size <= 50:
            raise RuntimeError("REVIEW_SIZE must be between 1 and 50")
        return cls(
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_owner_chat_id=int(_required("TELEGRAM_OWNER_CHAT_ID")),
            telegram_webhook_secret=_required("TELEGRAM_WEBHOOK_SECRET"),
            gemini_api_key=_required("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
            cron_secret=_required("CRON_SECRET"),
            storage_backend=backend,
            sqlite_path=Path(os.getenv("SQLITE_PATH", "data/vocabulary.sqlite3")),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            review_size=review_size,
            timezone=os.getenv("TIMEZONE", "Asia/Taipei").strip(),
        )
