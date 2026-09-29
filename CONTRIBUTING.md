# Contributing to Mnemosyne

Thanks for helping improve Mnemosyne. The project is deliberately narrow: a self-hosted,
single-user Telegram workflow for English vocabulary cards and recall-graded review.

## Good contributions

- reproducible bug fixes
- clearer setup, deployment, or troubleshooting documentation
- tests for reliability, security boundaries, and data integrity
- small usability improvements that preserve the owner-only product model

Large feature proposals, new infrastructure providers, and multi-user support should begin with a
feature request. This avoids implementation work that conflicts with the project's current scope.

Security vulnerabilities do not belong in public issues. Follow [SECURITY.md](SECURITY.md).

## Local setup

Requirements: Python 3.11+ and PowerShell.

```powershell
git clone https://github.com/Yili-code/Mnemosyne.git
cd Mnemosyne
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Use placeholder or test credentials for local development. Never include tokens, chat IDs, live user
data, or populated `.env` files in issues, commits, screenshots, or test fixtures.

## Required checks

Run these before opening a pull request:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

Tests must stay offline and deterministic. Mock Telegram, Gemini, Firestore, and Cloud Tasks rather
than spending credentials or depending on live services.

## Pull requests

Keep each pull request focused on one problem. Include:

1. the user-visible or operational problem
2. the chosen solution and important trade-offs
3. tests or other evidence that demonstrate the change
4. documentation changes when configuration or behavior changes

Do not claim live integration success from unit tests alone. If you performed a live check, describe
the boundary tested without including credentials or user data.
