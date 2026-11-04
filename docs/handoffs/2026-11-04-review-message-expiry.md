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


## Live verification and activation (2026-11-04T13:31:57.338106+08:00)

Implementation commit 30e5468 was pushed to origin/codex/batch-recall. Committed source was built
as mnemosyne-00030-nur with zero traffic first. Environment values/secret references and runtime
identity matched the previous service. Health, invalid-secret rejection, wrong-owner rejection,
and unknown-session no-op passed on the candidate.

An isolated live test seeded one disposable word/session, invoked the actual candidate delivery
worker, and verified that the runtime created a real Cloud Task with schedule_time exactly three
hours after the recorded send time. The task targeted the canonical /tasks/cleanup-review route.
After reading the real schedule, the test task was cancelled and ONLY that disposable session's
send timestamp was aged by three hours. The actual cleanup endpoint deleted the real Telegram
message and expired the session without grading/removing its word. Then the test word/session
were removed. Hashes of every pre-existing word document matched before and after. This is an
accelerated expiry test, not observation of three hours of wall-clock execution. No real user
callback was fabricated; answered-message protection and races were tested offline.

Activated mnemosyne-00030-nur at 100% production traffic for the user's requested live setting.
Verified traffic allocation plus canonical service health and authenticated cleanup no-op after
cutover. Rollback target remains mnemosyne-00028-wuf. No main merge or webhook change. All private
credentials, deployment metadata, logs and test manifests remain ignored and uncommitted.

Complete: one daily automatic group (up to five words), three-hour unanswered-message cleanup,
111 offline tests, live runtime task creation, accelerated real deletion, and production activation.
Known bounds: manual /review is an explicit additional request; any successful reveal counts as a
response; prior untracked messages are not backfilled; queue delays/retries can postpone deletion;
ambiguous send-before-persistence remains at-least-once. Queue-less local mode requires an external
cleanup caller. The baseline hook lint problem is unchanged.

This final deployment receipt is prepared as a documentation-only commit and push after the
implementation commit. No further code changes or repeat tests are required for this receipt.
Next: normal scheduled usage; no automatic wall-clock follow-up monitor was requested or created.
