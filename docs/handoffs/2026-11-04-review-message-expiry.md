# Daily review limit and unanswered-message expiry

Updated: 2026-11-04T13:22:49.314762+08:00
Baseline: 36097ec; branch codex/batch-recall, synchronized and clean at task start.

User requests one group per day and automatic deletion after three hours without a response.
Interpretation stated in chat: delete only the unanswered Telegram review message, never vocabulary
or learning records. Any successful reveal/selection/completion counts as responding. Scheduled
review selects at most five words in a single group. Manual /review remains an explicit request.

Plan: persist delivered message IDs/times; enqueue delayed Cloud Tasks for three-hour cleanup;
atomically expire untouched groups before deletion so callbacks cannot race grading. Preserve
answered groups, reject early/mismatched cleanup requests, retry transient delete/enqueue failures.
Use the existing owner-only and cron-secret boundaries. Build and verify before production update.
State: implementation in progress; no new deployment, commit or push yet.


## Implementation and offline verification (2026-11-04T13:27:21.449519+08:00)

Implemented a single group of min(REVIEW_SIZE, 5) words per daily selection. Existing day-based
idempotency remains; manual requests explicitly bypass the daily guard but return only one group.
Persist every delivered message ID/time in ReviewBatch. Queue a named cleanup task at sent_at+3h.
Worker validates cron secret, owner, stored message ID, elapsed time and untouched state. SQLite
and Firestore atomically expire the session before Telegram deletion; an answered group remains
visible and racing callbacks cannot grade an expired group. A missing Telegram message is an
idempotent success; other delete failures are retriable. Delivery retries reuse recorded messages
when cleanup enqueueing failed. Direct delivery can use a separately configured cleanup queue;
queue-less local instances require an external cleanup caller. Old messages are not backfilled.

Verification: 111 offline tests passed (1 dependency deprecation warning); app lint and format
passed (39 files); git diff --check passed. Includes both storage transaction adapters, deadline
boundary, answered/unknown messages, duplicate message registration, queue scheduling/naming,
owner/secret checks, deletion retry, enqueue failure without resending, and reveal/expiry race.
Full-repository hook lint issue remains the previously documented baseline; hooks were not changed.

Live read-only check confirms production is still mnemosyne-00028-wuf at 100% traffic, with
cloud_tasks delivery. Previous configuration saved privately for rollback; no credentials/logs
will be committed. Preparing one atomic implementation commit and push, followed by a zero-traffic
build and smoke checks before activation of the requested live behavior. No live expiry claim yet.
