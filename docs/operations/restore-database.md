# Neon production database restore

Use this only for confirmed data damage or an approved incompatible migration.
An application-only failure uses `rollback.md`; restoring a database is not a
routine deploy step. The successful isolated drill in
`2026-08-12-database-drills.md` is evidence that the procedure can materialize
and validate a point-in-time branch within Neon's available restore window.

## 1. Contain and choose the restore point

1. Record the incident time, serving code revision, last known-good database
   time, affected tables, and decision owner. Do not put rows, credentials, or
   user data in the incident record.
2. Stop application writes before restoring. Make the production service
   private or route traffic to a documented maintenance response, and pause
   every Scheduler or job capable of writing. Read back those states.
3. Preserve the damaged branch. Do not reset, delete, or mutate it while the
   restore is being validated.
4. Select a point immediately before the first known bad write and confirm it
   is inside the provider's currently displayed restore window.

## 2. Materialize and validate an isolated branch

Create a temporary Neon branch from the production branch at the exact restore
timestamp. Give it a descriptive incident name and the shortest supported
automatic expiration. Do not clone the database into local storage.

Connect with a temporary direct schema-owner URL held only in process memory.
Require `sslmode=verify-full`, the system CA bundle, and
`channel_binding=require`. Validate, without printing data:

- expected Django migrations are applied and `migrate --check --plan` reports
  no pending operations for the selected release;
- invariant row counts and authoritative-release uniqueness are plausible;
- the suspected corruption is absent at the selected time;
- identity, billing, job-run, import, and outbox receipts are internally
  consistent; and
- a read-only `/health/ready` execution from the compatible immutable image
  succeeds against the candidate branch.

If validation fails, keep production writes stopped and create a different
isolated point-in-time branch. Never repair the candidate by hand to make the
checks pass.

## 3. Cut over through scoped secrets

1. Create new least-privilege runtime and schema credentials on the validated
   branch. Keep web/jobs pooled and migration direct.
2. Create new versions of the existing `illinicover-web`,
   `illinicover-jobs`, and `illinicover-migrate` bundles from mode-0600
   temporary files. Never log or paste connection strings.
3. Deploy the known-compatible immutable image with its exact `CODE_REVISION`.
   Run migration first, then deep readiness, API status, privacy, and Admin
   static probes while the service remains private.
4. Read back image digest, code revision, deployment environment, database
   mode, secret-version routing, serving revision, and paused Scheduler state.
5. Restore public invocation and resume only the schedules that were enabled
   before containment after every acceptance check succeeds.

## 4. Reconcile and close

Re-run idempotent imports and bounded provider reconciliation from the first
restored timestamp forward. Check RevenueCat, outbox delivery, job receipts,
account/deletion receipts, and model/deal authority. Do not synthesize missing
success receipts or edit entitlement/model authority directly.

Keep the former damaged branch and prior secret versions for the explicitly
approved observation window. If the restored branch is wrong, stop writes and
route the service back only when the former branch is still the safer,
schema-compatible authority; otherwise repeat the point-in-time procedure from
a newly validated timestamp. Database rollback and Cloud Run traffic rollback
remain separate decisions.

After the incident owner accepts reconciliation, revoke obsolete database
credentials, destroy superseded secret versions, delete the exact temporary or
damaged branch selected for cleanup, and read back absence. Record only branch
IDs, timestamps, counts, immutable revisions, and provider audit links. Confirm
Neon and GCP usage remain inside the intended free-tier envelope.
