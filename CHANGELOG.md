# Changelog

This file records user-visible changes to Mnemosyne. The project follows semantic versioning after
the initial alpha release.

## 0.1.0 - 2026-09-29

Initial public alpha.

### Learning workflow

- Generate structured English vocabulary cards with Traditional Chinese explanations through
  Gemini.
- Save headwords and useful related vocabulary while filtering routine grammatical and word-family
  derivatives.
- Review due words with Hard, Good, and Easy recall grades using an SM-2-inspired scheduler.
- Search one stored word without generating content or changing learning data.
- List saved words and clear learning data through an explicit owner-only confirmation flow.

### Reliability and deployment

- Run locally with SQLite or on Google Cloud Run with Firestore.
- Deduplicate Telegram updates and daily review deliveries.
- Persist failed Gemini requests and retry them with capped backoff.
- Queue review-card delivery through Cloud Tasks with bounded rate and concurrency.
- Protect webhook and scheduler endpoints with separate secrets.
- Document Cloud Run, Firestore, Secret Manager, Cloud Tasks, Cloud Scheduler, cost controls, and
  production verification.

### Known limits

- Mnemosyne is a self-hosted, single-user bot; there is no public hosted instance.
- English headwords produce Traditional Chinese learning content.
- Structured output is validated, but semantic accuracy still depends on the configured Gemini
  model.
- The release is alpha and does not promise configuration or storage compatibility with later
  versions.
