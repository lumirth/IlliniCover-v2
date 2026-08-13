# Backend deployment

The production default is the dedicated Google Cloud project `illinicover`
(project number `1068900473446`) in `us-east5`. The deploy script accepts a
`GCP_PROJECT_ID` override, but explicitly refuses the unrelated personal
project `lukashermes`.

## Free-tier operating envelope

The checked-in Cloud Run service is request-based and intentionally bounded:

- minimum instances: 0;
- maximum instances: 3;
- one vCPU, CPU throttled outside requests, startup boost disabled;
- 512 MiB memory;
- 40 concurrent requests;
- 30-second request timeout;
- one Gunicorn process with four threads inside the 512 MiB envelope;
- no always-on worker, Redis, Celery, or queue service.

Migration, bootstrap, refresh, and nightly maintenance use the same scale-to-zero
image, one task, 512 MiB, and one retry. The routine GitHub release executes
migration before rolling the public service, then requires candidate and stable
readiness to pass. Bootstrap is explicit (`RUN_BOOTSTRAP_ON_RELEASE=true`) and
is not part of routine post-merge deployment. One Cloud Scheduler job in
`us-east4` invokes the
`us-east5` nightly job once daily, within the free Scheduler allowance.

The nightly schedule is a release transaction guard, not an independent race.
Before replacing any Cloud Run job image, the script discovers the exact
Scheduler state and pauses an enabled job. A previously paused job stays
paused. Because Cloud Scheduler exposes job state as output-only and has no
create-paused operation, the first release creates the job on a syntactically
valid but impossible February 31 schedule, immediately pauses and verifies it,
then installs the real target and schedule while it remains paused. Migration,
an explicitly requested bootstrap, web rollout, and every smoke probe must all succeed before a newly
created or previously enabled schedule is resumed. Before pausing an enabled
schedule, the release writes a provider-persisted resume-intent marker. The exit
and signal traps make a best-effort pause and require paused-state readback on
failure; the next release recognizes that marker and restores the original
enabled intent only after every release gate passes. A paused schedule without
the marker is intentional and is never resumed by a release.

Free allotments are aggregated by billing account and budgets are alerts, not
hard spending caps. This configuration minimizes expected beta usage but cannot
guarantee a zero invoice if another project consumes a shared allowance or the
service exceeds an allowance. At release time, check billing-account usage as
well as the project budget alerts.

Artifact Registry's free storage allowance is 0.5 GiB-month per billing account,
not per project. The owner explicitly accepts modest storage charges during
release work, so the workflows and manual helper enforce a finite
1,000,000,000-byte repository budget rather than treating the free allowance as
a hard release boundary. A new build still requires 256 MiB of headroom; an
image that nevertheless crosses the budget is deleted by its exact newly built,
still-unserved digest and verified no longer addressable.
The provider's billed-size counter may lag while unreferenced layers are
collected asynchronously. Existing
commit/source tags are reused, and both base images are digest-pinned, so a
repeat release cannot manufacture another digest. The repository receipt does
not see other projects on the billing account, so billing-account-wide usage
still belongs in cost review even though zero cost is no longer a release gate.

## Secrets

Use three Secret Manager JSON bundles, with one active version each:

- `illinicover-web`: pooled application database credential, Django/HMAC,
  webhook, email, and optional Sentry secrets;
- `illinicover-migrate`: direct schema-owner credential and Django secret only;
- `illinicover-jobs`: pooled least-privilege application credential, Django/HMAC,
  and only the provider secrets needed by scheduled jobs.

This remains under the six-active-version free allowance while ensuring a web
process compromise does not disclose the schema owner or direct endpoint. Each
bundle is mounted as `ILLINICOVER_SECRETS_JSON`, a JSON object of strings.

```text
DATABASE_URL
DJANGO_SECRET_KEY
SESSION_TOKEN_HMAC_KEY
INSTALLATION_TOKEN_HMAC_KEY
NETWORK_METADATA_HMAC_KEY
REVENUECAT_WEBHOOK_AUTH_SECRET
REVENUECAT_WEBHOOK_SIGNATURE_SECRET
REVENUECAT_SECRET_API_KEY
EMAIL_HOST
EMAIL_PORT
EMAIL_HOST_USER
EMAIL_HOST_PASSWORD
EMAIL_USE_TLS
DEFAULT_FROM_EMAIL
```

The web process, bootstrap, refresh, and nightly jobs set
`DATABASE_MODE=pooled` and receive only `DATABASE_URL`. Migration alone sets
`DATABASE_MODE=direct` and receives `DATABASE_URL_DIRECT`. Normal jobs use a
short transaction-scoped advisory lock only to establish a durable JobRun
receipt, so they are compatible with Neon transaction pooling. Ordinary
environment variables with the names used in
`.env.example` override matching bundle keys. Neither the JSON value nor any
individual secret is logged.

Network rate-limit identity is derived from the trusted right-hand suffix of
`X-Forwarded-For`, never its attacker-controlled prefix. The checked Cloud Run
deployment uses direct public `run.app` ingress, so
`TRUSTED_XFF_PROXY_HOPS=0` selects the right-most address appended by the
Cloud Run frontend. The setting counts additional trusted proxies after that
address; no separate External Application Load Balancer is provisioned. If a
custom load balancer, CDN, or other proxy is added, treat the value as invalid
until the deployed chain is captured and verified. During the initial live
smoke, send requests with different attacker-controlled XFF prefixes from one
client and verify they map to one keyed network identity; do not log or retain
the raw header for this check.

Cloud Run emits infrastructure request logs that can include requester IP
addresses. Before building or serving a release, the deploy script idempotently
adds the exact `log_id("run.googleapis.com/requests")` exclusion to the
project's `_Default` sink and verifies readback, so these logs are not stored in
the project's log buckets or counted toward its storage allotment. Gunicorn
access logging is disabled as well. Safe structured application and job receipts
remain available for release correlation and incident diagnosis.

Production auth email and RevenueCat authority are explicit release gates. The
process-only liveness endpoint remains available for diagnosis, but deep
readiness refuses a production or preview release until SMTP host/credentials,
RevenueCat webhook authentication/signing, and the RevenueCat secret API key
are all present. Development and tests intentionally use console/locmem email
backends.

## Release sequence

1. The routine path is `.github/workflows/deploy.yml` on every advance of
   `main`. Its provider-free classifier first compares the exact push range.
   Changes to `server/`, dependencies, shipped API/data/policy artifacts,
   container and Cloud Run configuration, or release/deployment scripts proceed
   to GCP WIF using the exact 40-character Git commit SHA. iOS-only and
   non-runtime documentation advances write a visible no-op receipt and do not
   authenticate to GCP, build an image, migrate, or deploy. An initial push,
   missing/non-ancestor previous commit, or change to the deployment workflow
   itself fails safe to the release path. Verify the GitHub variables and
   provider claim restriction in `docs/operations/github-wif.md`.
2. The manual first-cutover/recovery helper may compute a source revision with
   `python3 scripts/release/source_revision.py`. It hashes, with unambiguous
   framing, the exact `.gcloudignore` file set and rejects concurrent edits.
   Local acceptance artifacts, DerivedData, test/type-check caches, and coverage
   output are excluded and rejected defensively if they ever enter that set.
3. Set `PUBLIC_API_ORIGIN` to the actual service `run.app` origin (or configured
   custom origin); the script fails closed if it is omitted so auth email links
   never use an invented host.
4. Create or update the scoped secret versions without printing their values.
5. Run `ops/deployment/deploy-cloud-run.sh`; it captures and pauses Scheduler
   before any job image swap, runs migration before a no-traffic candidate,
   narrows Scheduler's invoker role to the nightly job, records the previous
   serving revision, and checks the live, ready, status, privacy, and static
   surfaces before promotion. The first service is created private and made
   public only after authenticated readiness. Bootstrap runs only when
   `RUN_BOOTSTRAP_ON_RELEASE=true` is explicit. Before mutation, every existing
   job's complete functional template is captured. A failed release replaces
   the prior image, command, arguments, environment, secret references, service
   account, resources, retry policy, and timeout as one manifest and verifies
   the complete readback before it may delete the rejected image.
6. Verify `/health/live`, `/health/ready`, `/api/v2/status`, and one Admin CSS URL.
7. Export the server contract and verify no unexplained diff.

For the initial default-URL cutover, the predicted origin is
`https://illinicover-api-1068900473446.us-east5.run.app`. From the repository
root, the exact command is:

```bash
release_revision="$(python3 scripts/release/source_revision.py)"
GCP_PROJECT_ID=illinicover \
PUBLIC_API_ORIGIN=https://illinicover-api-1068900473446.us-east5.run.app \
CODE_REVISION="$release_revision" \
IMAGE_TAG="$release_revision" \
ops/deployment/deploy-cloud-run.sh
```

Do not reuse a revision value after changing an uploaded file; recompute it
immediately before the release. The script independently checks the value.

Identity migration `identity.0003` adds client-keyed installation and deletion
state. Migration `identity.0004` then creates durable link-request receipts,
backfills the initial request UUID for every existing link, and removes the
superseded one-request column. The HTTP cutover is intentionally clean rather
than backward-compatible: installation creation, installation rotation, actor
linking, and account deletion require their documented client UUID bodies.
Run migrations immediately before the web rollout and do not serve the old web
revision after `identity.0004`, because it still writes the removed link column.
Ship an iOS build generated from the same OpenAPI revision; an older client
receives HTTP 422 for these writes. There are no beta users requiring a
compatibility window.

Promote an unretired shadow release with
`python server/manage.py promote_cover_model <release-uuid>`. A first promotion
of a challenger additionally requires the exact receipt UUID from:

```bash
python server/manage.py evaluate_cover_challenger <release-uuid> \
  --cutoff <RFC3339-timestamp>
python server/manage.py promote_cover_model <release-uuid> \
  --evaluation-receipt <receipt-uuid>
```

The evaluation command freezes the admitted completed-night population after
the challenger's training cutoff and scores the challenger and its bound
authoritative baseline on the same rows. The checked-in
`chronological_holdout_v1` policy requires at least four service nights and 20
common predictions, strict MAE improvement, no regression in zero/high-cover
Brier score or interval score, MAE at most 800 cents, interval coverage at
least 0.70, mean interval width at most 2,000 cents, and every venue MAE at
most 1,000 cents. Unavailable context, sparse, nowcast, campus, and post-launch
dimensions are recorded as non-evaluable rather than silently omitted. The
receipt binds both artifacts, both training/evaluation revisions, the exact
selected-row hash, evaluator code revision, metrics, gates, and policy under a
canonical SHA-256.

The promotion command
validates the historical artifact and training revision, serializes execution
under the direct-database job lock, and writes both a job receipt and audit row.
An unpromoted challenger is rejected unless its immutable evaluation receipt
records a winning `chronological_holdout_v1` comparison against the still-current
baseline, is the newest known comparison for that pair, and marks it promotion
eligible. Free-form flags on the model release
are never promotion authority. A previously promoted release remains
reproducible for historical inspection, but its database release identity is
permanently retired and cannot become authoritative again. The nightly shadow
job does not auto-promote or manufacture approval; evaluation and promotion
remain explicit operator actions.

### Recovering from a bad model promotion

Release lifecycle timestamps are append-only authority history. Never clear a
retired release's `retired_at`, reuse its UUID or `model_version`, or copy its
old evaluation receipt. `promote_cover_model` deliberately rejects that path.

To restore previously accepted prediction behavior, register a new
`historical_challenger` release under a fresh UUID and unique model version:

```bash
python server/manage.py issue_cover_model_recovery <retired-release-uuid> \
  --model-version <fresh-unique-version>
```

The command clones the retired release's immutable historical behavior and
training revision into a new non-authoritative candidate, records the retired
source and current authoritative baseline, and never promotes it. Then run
`evaluate_cover_challenger` at a new chronological cutoff and promote only with
that new candidate's winning receipt. Evaluation begins after both the recovery
source's and current incumbent's training cutoffs, so neither artifact may be
scored on data it trained on. The receipt binds the reissued artifact, current
incumbent, frozen evaluation rows, evaluator revision, and current policy; an
old receipt is stale by construction.

`refresh_cover_models` remains the path for issuing a newly trained challenger;
it is not an exact behavioral clone. Until the newly issued recovery path is
drilled end to end in an isolated production-like database, treat recovery as a
corrective release rather than an instantaneous authority switch.

The Artifact Registry cleanup policy deletes versions older than seven days,
retains the two newest versions per package, and explicitly preserves images
tagged `production-serving`, `production-rollback`, and `preview-serving`.

Database restore and model rollback remain separate release gates; a successful
container deployment does not prove either one.

## Local release gates and external CI

`scripts/ci/all.sh` is a local convenience aggregate for backend,
OpenAPI, data, canonical fixtures, and repository operations checks. GitHub
workflow path policy remains visible in `.github/workflows/ci.yml`; the Apple
lane remains owned by Xcode Cloud and the checked-in iOS tasks rather than this
aggregate.

Repository workflows are checked in for selective PR CI, automatic production
deployment from `main`, optional shared preview, and model evaluation. The
production and preview WIF providers, repository variables, six-version secret
inventory, and isolated Neon preview project have provider readback in
`docs/operations/2026-08-12-gcp-release-preflight.md`. That bootstrap is not a
workflow-execution receipt: the final v2 tree still needs one committed Git SHA,
the required GitHub checks and deployment must run for that SHA, and Artifact
Registry's provider counter must first fall below the checked-in build ceiling.
Xcode Cloud/TestFlight setup and execution remain separate Apple-side gates.
