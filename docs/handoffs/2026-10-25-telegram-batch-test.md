# Live Telegram batch test

Updated: 2026-10-25T23:22:14.254982+08:00
Baseline: 12ead39; branch codex/batch-recall.

User explicitly authorized deploying the new version and testing real Telegram buttons.
Previous production revision: mnemosyne-00027-ngj. Deployment configuration
was saved locally under ignored .private; it must not be committed. Build source is a git archive
of the committed application, excluding local credentials, virtual environment and unrelated work.

Plan: deploy a no-traffic tagged revision, check health, then switch existing service traffic while
preserving env/secrets and the webhook. Send a clearly labeled batch of isolated test words and
verify real webhook callbacks, durable selection and completion. Preserve existing user words and
progress; clean up only test-created IDs. No webhook re-registration or pending-update deletion.

Status: production metadata verified, deployment/test preparation in progress. No live success yet.
Next: deploy, verify revision, create isolated data, perform real-button test, clean up, record evidence.

## Interrupted live interaction (2026-10-25T23:29:21.2297328+08:00)

User explicitly authorized the deployment, then separately authorized the exact 100% production cutover after automatic approval review rejected the initial combined cutover request. Revision mnemosyne-00028-wuf now serves 100% production traffic, verified from Cloud Run metadata. Previous revision mnemosyne-00027-ngj remains the rollback target. Health, invalid-secret rejection and owner boundary checks passed; environment and runtime identity were verified unchanged. Existing webhook was not changed; read-only Telegram checks showed valid bot credentials, configured webhook, zero pending updates and no last error.
Five uniquely named disposable test words and one durable batch were created, then sent to the configured owner chat. Before setup, hashes of the existing 550 word documents were saved privately; no existing word was modified by this test setup. Test metadata and cleanup helper are ignored under .private/batch-live-test.json and .private/batch_live_test.py; never commit them.
Computer Use selected the Mnemosyne chat in Unigram. At the next screenshot, the user physically pressed Escape. Computer Use explicitly reported a stop; no further UI actions were performed. Real reveal/select/complete callbacks have NOT been verified. Test data remains for manual completion or later cleanup. Do not claim the entire live test passed.
Next: user can manually operate the already sent test batch, then check persistent session and word schedules using the private status helper; clean up only the five recorded test IDs and recorded session. Confirm hashes of all non-test words before/after cleanup. No callback or cleanup has been simulated. This handoff update is local and uncommitted; no new commit/push was performed during the interrupted live-test task.


## Completed live verification (2026-10-25T23:31:16.327494+08:00)

The user manually clicked the real Telegram controls after the Computer Use interruption.
Firestore inspection confirmed stage=completed, revision=3, selected unfamiliar index=[0],
remembered_count=4, unfamiliar_count=1, skipped_count=0. Every test word had review_count=1;
the selected word had interval_days=10/1440 and the other four had interval_days=3. This verifies
actual Telegram callbacks through the deployed webhook and real Firestore completion, rather
than synthetic callback injection. Selection undo and duplicate live clicks were not exercised;
their evidence remains the offline suite. The batch was sent directly using Telegram API, so
this test does not establish Cloud Tasks or Scheduler delivery. Gemini was not invoked.

The cleanup helper removed exactly the five recorded disposable word IDs and the recorded batch
session. Hashes of all 550 original word documents matched the pre-test baseline before and after
cleanup. A completion notice was sent to the configured owner chat. No original words, grades,
webhook configuration or pending updates were changed by the test. Private manifests, logs and
credentials remain ignored and are excluded from commits.

Deployment remains on mnemosyne-00028-wuf (100% traffic verified at cutover); previous revision
mnemosyne-00027-ngj is available for rollback. No source change or main merge was made. This
verification record is prepared as an atomic documentation commit and push on codex/batch-recall;
check the remote branch for publication. No new application test run is needed for this record-only
change. Next: normal use via /review; validate scheduled queue delivery separately if required.
