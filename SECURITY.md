# Security Policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature instead of opening a public issue.
Include the affected endpoint, reproduction steps, expected impact, and any suggested mitigation.
Do not include live credentials, Telegram chat IDs, or user data in the report.

## Security model

- Telegram webhook requests must include the configured webhook secret.
- Scheduler endpoints use a separate cron secret.
- Cloud Run receives credentials from Secret Manager; credentials are never built into the image.
- The runtime service account should have only Secret Manager accessor and Firestore data-user roles.
- Telegram updates are idempotent, reducing duplicate model calls and writes during webhook retries.

## Deployment responsibility

This repository contains application code and deployment guidance, not managed infrastructure.
Operators are responsible for rotating credentials, reviewing IAM, enabling billing alerts, and
keeping dependencies and the deployed container current.
