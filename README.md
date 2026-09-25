# Mnemosyne

> A production-oriented Telegram vocabulary learning bot powered by Gemini, FastAPI, Firestore,
> and Google Cloud Run.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Google Cloud Run](https://img.shields.io/badge/Google_Cloud-Run-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![CI](https://github.com/Yili-code/Mnemosyne/actions/workflows/ci.yml/badge.svg)](https://github.com/Yili-code/Mnemosyne/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Mnemosyne turns a quick vocabulary lookup into a durable learning loop. Send one English word to
the Telegram bot and receive a concise card with KK phonetics, Traditional Chinese definitions,
usage notes, collocations, examples, and semantically related vocabulary. Every result is stored for
weighted daily review.

The project is intentionally small, but it treats external AI, webhooks, scheduled jobs, secrets,
and persistent state as production concerns rather than demo details.

## Why it exists

A dictionary helps with recognition now; learning requires recall later. Mnemosyne connects both:

1. Look up a word in Telegram.
2. Generate a schema-validated learning card with Gemini.
3. Reject low-value inflections and routine word-family derivatives.
4. Save the headword and related vocabulary.
5. Resurface newer and overdue words through weighted review.

## Highlights

- **Structured AI output** — Pydantic validates every Gemini response before persistence.
- **Useful related vocabulary** — deterministic rules remove plurals, tense variants, and ordinary
  derivations that a prompt alone may still produce.
- **Durable retry queue** — failed generations survive process restarts and retry with capped
  backoff instead of asking the user to resend a word.
- **Storage abstraction** — SQLite supports local development; Firestore supports stateless Cloud
  Run deployments through the same repository contract.
- **Idempotent delivery** — Telegram update IDs and daily-delivery records prevent duplicate work.
- **Least-privilege deployment** — runtime credentials live in Secret Manager and Firestore access
  comes from the Cloud Run service account.
- **Cost-aware operation** — scale-to-zero compute, bounded concurrency, one retry item per request,
  and documented billing controls.

## Example

Send:

```text
meticulous
```

Receive a card shaped like:

```text
meticulous
[məˈtɪkjələs] · adjective

中文釋義
一絲不苟的；非常仔細的

用法
常用於描述對細節極度謹慎的人或工作方式。

例句
She kept meticulous records of every transaction.

相關單字
thorough [ˈθɝo]
徹底的 · emphasizes completeness
The team conducted a thorough review.
```

## Telegram commands

| Command | Purpose |
| --- | --- |
| `word` | Generate and save a vocabulary card |
| `/review` | Start an additional weighted review without examples |
| `/words` | List every stored word, part of speech, and Chinese meaning |
| `/stats` | Show the number of stored words |
| `/help` | Show in-bot usage instructions |

The bot responds only to the configured owner's private chat.

## Architecture

```text
Telegram
   │ signed webhook
   ▼
Cloud Run / FastAPI ───────► Gemini API
   │                            │
   │ validated card             │ transient or validation failure
   ▼                            ▼
Firestore ◄──────────── pending_words queue
   │                            ▲
   │ weighted vocabulary       │ every 10 minutes
   ▼                            │
Telegram ◄──────────── Cloud Scheduler
```

Cloud Run is ephemeral; Firestore owns durable state. Cloud Scheduler invokes protected endpoints
for daily review and failed-word recovery. This separation keeps request handling stateless without
pretending a container's local SQLite file is permanent cloud storage.

## Reliability model

Gemini failures are classified without logging credentials or full provider responses. Failed words
are persisted and retried after 15 minutes, 1 hour, 6 hours, and then once per day until successful.
Firestore claims use a short transactional lease so overlapping scheduler invocations do not process
the same item concurrently.

The system combines three control layers:

1. **Semantic control:** Gemini selects useful related vocabulary.
2. **Structural control:** Pydantic constrains fields, types, and lengths.
3. **Deterministic control:** Python rules reject predictable word-family noise.

This boundary matters because prompting is probabilistic; product rules should be testable.

## Weighted review

Review priority is calculated as:

```text
5 / (1 + review_count) + 1 + min(days_since_review, 30) / 7
```

The first term favors unfamiliar words. The second favors words not reviewed recently. Sampling is
weighted and without replacement, so one review does not repeat the same word.

## Quick start

Requirements: Python 3.11+.

```powershell
git clone https://github.com/Yili-code/Mnemosyne.git
cd Mnemosyne
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Fill in `.env`, then run locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn vocab_bot.app:app --reload
```

Local development defaults to SQLite. Never commit the populated `.env` or local database.

## Configuration

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token issued by BotFather |
| `TELEGRAM_OWNER_CHAT_ID` | Only private chat allowed to use the bot |
| `TELEGRAM_WEBHOOK_SECRET` | Validates Telegram webhook requests |
| `GEMINI_API_KEY` | Gemini API credential |
| `GEMINI_MODEL` | Model ID used for structured generation |
| `CRON_SECRET` | Protects scheduler endpoints |
| `STORAGE_BACKEND` | `sqlite` locally or `firestore` in production |
| `GOOGLE_CLOUD_PROJECT` | Firestore project when using the cloud backend |
| `REVIEW_SIZE` | Number of words in a daily review |
| `TIMEZONE` | Review timezone, defaulting to `Asia/Taipei` |

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete Cloud Run, Firestore, IAM, Secret Manager,
webhook, scheduler, billing, and troubleshooting walkthrough.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

The automated suite covers input normalization, derivative filtering, SQLite persistence, retry
backoff, idempotency, weighted selection, Gemini payload shape, and Telegram rendering. The deployed
system has also been exercised end to end with Telegram, Gemini, Cloud Run, Firestore, Secret
Manager, and Cloud Scheduler; credentials and live user data are intentionally not part of this
repository.

## Project layout

```text
src/vocab_bot/
├── app.py          FastAPI endpoints and dependency wiring
├── config.py       Environment configuration
├── gemini.py       Structured generation and provider error boundaries
├── models.py       Validated domain models
├── repository.py   SQLite and Firestore implementations
├── service.py      Application workflow and retry policy
├── telegram.py     Telegram client and HTML rendering
└── word_rules.py   Input and derivative filters

scripts/
└── setup_webhook.py

tests/
└── unit and service-level behavior tests
```

## Security

Do not place real credentials in issues, logs, screenshots, or commits. Production secrets belong in
Google Secret Manager, and the Cloud Run service account should receive only the permissions it
needs. See [SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## License

Released under the [MIT License](LICENSE).
