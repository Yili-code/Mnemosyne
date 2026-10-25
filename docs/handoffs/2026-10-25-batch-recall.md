# Batch recall review

Updated: 2026-10-25T23:17:54.942286+08:00
Baseline: origin/main df8afe2; branch codex/batch-recall.

## Scope and isolation
User authorized preserving local work and implementing only grouped recall from the latest remote.
Fetch succeeded before branch creation. A verified local ZIP contains all 29 modified/untracked
files from the original checkout. All 29 hashes still match after implementation. The original
checkout remains on main with its unpublished work and is NOT claimed synchronized. Source context,
profiles and Free/Pro changes remain isolated there. No hook or trust settings were modified.

## Implemented behavior
- Existing REVIEW_SIZE bounds the total selection (default 20); groups contain at most five words.
- English-only prompts precede one reveal per group. Toggle only forgotten/uncertain expressions.
- Only explicit completion after reveal changes schedules: remembered maps to Good, unfamiliar to
  Again. This grouped flow never deletes words. Ten minutes is due eligibility, not a new push timer.
- SQLite and Firestore store durable sessions. Completion and unchanged eligible word schedules
  commit together. Revision checks prevent replayed selections and duplicate completion; snapshot
  checks protect words reviewed elsewhere, refreshed, deleted or recreated.
- Telegram edits the same message. Retried callbacks restore durable UI state after a display error.
- Cloud Tasks carries a batch ID and uses it for deterministic naming. Old single-card payloads and
  grading callbacks remain compatible. New payloads/callbacks require the new worker on rollback.
- Sessions expire after seven days. Expiry blocks grading but does not prune storage; /clear deletes
  sessions along with learning data. Answer previews are bounded; /search retains saved details.

## Files
models.py, batch_review.py, batch_store.py, repository.py, service.py, telegram.py, review_tasks.py;
batch/service/task tests; README.md, DEPLOYMENT.md, CHANGELOG.md and this handoff.

## Verification
- Offline pytest: 98 passed (0.97 seconds on the final run), no skipped tests.
- Coverage includes both storage adapters' transaction bodies, SQLite restart persistence,
  concurrent completion, all-or-nothing rollback, missing/expired/stale sessions, selection undo,
  owner/private-chat enforcement, completed/cleared queued sessions, callback acknowledgement and
  UI errors, bounded escaped Telegram text and callback data, and stable Cloud Tasks identities.
- Firestore tests use a controlled in-memory client, not a live database or emulator. SQLite
  concurrency tests use multiple connections. No live Telegram/Gemini/Firestore/Tasks calls.
- ruff check --exclude .codex .: passed; format --check --exclude .codex .: 36 files formatted.
- git diff --check: passed.
- Required unfiltered Ruff checks were also run: the pre-existing .codex/session_sync.py has 11 lint
  findings (I001=1, E501=9, SIM105=1) and needs formatting. Its origin/main version reproduces the
  same 11 findings. The script and lint configuration remain unchanged. Full repository checks and
  CI must not be described as green; the existing CI lint step will encounter this baseline issue.

## Delivery and next steps
One atomic task-only commit has been created; this final handoff update is included by amendment
before the first push to origin/codex/batch-recall. Publication follows this record. Confirm actual publication using Git history/upstream; no commit ID is embedded in its
own commit. No main merge, production deployment, direct test message, webhook update or live test. Existing
configured post-commit notifications may run normally.
Next: review the isolated branch; handle existing hook lint separately through the trusted hook
review workflow if needed; separately authorize deployment and verify the grouped flow on Telegram,
Firestore and Cloud Tasks. No learning-retention or adoption improvement is claimed from unit tests.
