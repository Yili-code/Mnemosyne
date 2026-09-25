from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


def main() -> None:
    load_dotenv()
    token = required("TELEGRAM_BOT_TOKEN")
    secret = required("TELEGRAM_WEBHOOK_SECRET")
    service_url = required("CLOUD_RUN_SERVICE_URL").rstrip("/")
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": f"{service_url}/telegram/webhook",
            "secret_token": secret,
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
        },
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise SystemExit("Telegram rejected the webhook configuration")
    print("Webhook configured successfully.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print(f"Webhook setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
