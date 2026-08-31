# Operations

Production is one immutable container revision, one Cloud Run web service, one
pre-traffic preparation job, one scheduled RevenueCat reconciliation job, and
one PostgreSQL database. Provider identities and readback are the release
record; the repository does not maintain parallel release receipts, manifests,
generic nightly jobs, or model promotion state.

## Invariants

- GitHub reaches Google Cloud only through short-lived Workload Identity
  Federation (WIF). There are no service-account keys or application secrets in
  GitHub.
- The deploy identity may build, deploy, change traffic, inspect secret
  metadata, and impersonate the three scoped service accounts. It cannot read
  secret payloads.
- `illinicover-web` receives a pooled database credential and runs both the web
  service and reconciliation command. The `illinicover-migrate` preparation
  job receives the direct schema credential. The web identity must never
  receive the direct bundle; the scheduler identity receives no secret.
- An Artifact Registry digest and the exact Git SHA identify the application.
  Migrations and canonical bootstrap finish before candidate traffic; tagged
  candidate and stable endpoints must pass provider readback and probes.
- RevenueCat is billing authority, but its availability does not gate core
  browsing, readiness, or deployment. Authenticated webhooks plus one daily
  reconciliation execution provide outage recovery.
- Routine releases require schema changes that remain compatible with the
  previously serving revision during candidate evaluation. A deliberately
  incompatible pre-alpha reset uses planned downtime and a fresh database;
  deployment does not add a compatibility layer.

## Local development and CI

```bash
mise install
mise run setup       # sync, PostgreSQL, migrate, canonical bootstrap
mise run up          # Django on 127.0.0.1:8000
mise run db:reset    # destructive only to the named local Compose volume
mise run down
```

Copying [`.env.example`](../../.env.example) happens automatically on first
setup. Put developer-only overrides in ignored `.env.local`; never place a
production credential there. Local scripts refuse to resolve provider secrets.

[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) runs one semantic
PostgreSQL lane for every pull request to `main`. Its entrypoint is
[`scripts/ci/check.sh`](../../scripts/ci/check.sh): shell and workflow syntax,
Ruff, mypy, Django checks, migration drift, migrations/bootstrap, OpenAPI
readback, and server tests. The exported contract must equal
[`api/openapi.json`](../../api/openapi.json). Native build and real-backend
acceptance use the commands in the [runtime runbook](../runbooks/runtime-acceptance.md).

## Production boundary

[`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) is the
normal post-merge path. It runs only for `main`, uses the GitHub `production`
environment, and serializes releases. Configure that environment with required
approval and these non-secret repository variables:

| Variable | Meaning |
| --- | --- |
| `GCP_PROJECT_ID` | Dedicated IlliniCover project; the script rejects `lukashermes` |
| `GCP_REGION` | Cloud Run, Cloud Build, and Artifact Registry region |
| `GCP_ARTIFACT_REPOSITORY` | Existing Docker repository name |
| `PRODUCTION_API_ORIGIN` | Path-free HTTPS public origin |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Exact WIF provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deployment service-account email |

The WIF provider must restrict assertions to the exact GitHub repository,
`refs/heads/main`, and preferably the exact
`.github/workflows/deploy.yml@refs/heads/main` workflow reference. Map only the
claims used by that condition. Grant the provider principal only
`roles/iam.workloadIdentityUser` on the deploy service account and keep its
policy free of key credentials.

Provision Cloud Build, Artifact Registry, Cloud Run, Cloud Scheduler, Secret
Manager, the two runtime service accounts, a no-secret
`illinicover-scheduler` service account, and the database before enabling the
workflow. Grant that scheduler identity `roles/run.invoker` only on
`illinicover-reconcile`; the deploy script enforces and reads back that binding.
The deploy identity needs only enough IAM to submit/read builds, push/describe
the repository and set its cleanup policy, deploy/read/execute the preparation
job, deploy/read/change traffic on the web service, deploy/read and set IAM on
the reconciliation job, create/update/read its Cloud Scheduler trigger,
describe versions of the two secrets, and act as the three service accounts.
It also lists/deletes failed revisions and services, removes the known obsolete
pre-alpha jobs/schedule during the explicit cutover, reads project IAM, and
mints an identity token to invoke a private first revision. Runtime identities
receive Secret Manager payload access only to their own bundle.

## Release transaction

The workflow builds `backend:${GITHUB_SHA}`, resolves its provider digest, then
calls [`ops/deployment/deploy-cloud-run.sh`](../../ops/deployment/deploy-cloud-run.sh)
with the digest, exact 40-character SHA, project, region, repository, and public
origin. Optional names default to `illinicover-api`, `illinicover-web`, and
`illinicover-migrate`.

The script:

1. resolves each secret's enabled numeric `latest` version without reading its
   payload and records the sole revision currently serving 100 percent;
2. deploys and reads back `illinicover-migrate`, refuses a blank or legacy
   database outside the explicit cutover, then runs `migrate` and the idempotent
   canonical `bootstrap` using the direct database bundle;
3. for an existing service, deploys the digest as a tagged, unauthenticated,
   no-traffic web revision using the pooled bundle and reads back image, SHA,
   mode, and secret version;
4. probes live, ready, status, and useful cover/deal payloads through the
   candidate tag;
5. moves 100 percent of traffic to the candidate, verifies the traffic pointer,
   repeats the probes through the public origin, then removes and verifies the
   temporary candidate tag;
6. deploys and reads back `illinicover-reconcile` with the same image/SHA and
   numeric pooled secret, binds only `illinicover-scheduler` as invoker, and
   creates or updates its daily `10:17 UTC` authenticated trigger in `us-east4`;
   and
7. after any failure following a candidate attempt, restores the previous web
   revision and removes the failed tag/revision.

A first deployment cannot use Cloud Run's `--no-traffic` flag. It creates the
initial revision without public invocation, probes its tagged URL with the
deploy identity, and grants public invocation only after those probes pass.
Any later failure deletes the new pre-alpha service and verifies absence with a
successful provider list read. No database migration is reversed automatically.

### One-time pre-alpha cutover

The consolidated `product.0001_initial` schema is not a migration path from the
retired application tables. Before the first release of this rewrite:

1. provision one empty production database and point both the pooled web bundle
   and direct migration bundle at it;
2. disable public writes during the cutover and manually dispatch the production
   workflow with `prealpha_cutover` checked;
3. let `verify_deploy_database --allow-empty` prove that the selected database is
   empty before migrations run; it still rejects any legacy or partial schema;
4. let the same transaction delete and verify absence of the obsolete
   `illinicover-nightly` schedule and the `illinicover-bootstrap`,
   `illinicover-nightly`, and `illinicover-refresh` jobs, and remove/read back a
   project-wide scheduler invoker grant, and refuse any project-level
   `allUsers` or `allAuthenticatedUsers` Cloud Run invoker grant;
5. accept the release only after the private candidate, public origin, sole
   reconciliation job, and sole schedule all pass readback; and
6. enumerate every retained Cloud Run revision and job and confirm that none
   references the retired `illinicover-jobs` secret or
   `illinicover-jobs@${GCP_PROJECT_ID}.iam.gserviceaccount.com`, then delete that
   secret and service account and prove both exact names absent with successful
   Secret Manager and IAM service-account list reads. A provider read failure is
   not evidence of absence.

Normal push deployments never set the cutover flag. They require the current
`product` migration lineage and fail closed if provider discovery cannot prove
whether a service or obsolete resource exists. Retire any old preview service,
preview jobs, preview database branch, preview secrets, and preview service
accounts by the same enumerate-references, delete, and successful-list-readback
procedure; these are post-acceptance retirement tasks, not part of the permanent
production deploy transaction.

The reconciliation job update happens only after candidate and public probes
pass. A failed later check may therefore leave that job on the new image while
web traffic returns to the previous revision. This is safe only under the
forward-compatible routine migration rule above: Cloud Run Job updates are
atomic, and overlapping reconciliation executions converge. For an
incompatible reset, disable the schedule during planned downtime and redeploy
the complete system against the fresh database.

## Application rollback

Use Cloud Run traffic rollback for a bad application revision, not for damaged
data. Get the known-good revision from Cloud Run audit/revision history and
first verify that every numeric secret version it references still exists.

```bash
gcloud run services update-traffic illinicover-api \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
  --to-revisions "${KNOWN_GOOD_REVISION}=100"
gcloud run services describe illinicover-api \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json
curl --fail --silent "$PRODUCTION_API_ORIGIN/health/live"
curl --fail --silent "$PRODUCTION_API_ORIGIN/health/ready"
curl --fail --silent "$PRODUCTION_API_ORIGIN/api/status"
```

Accept the rollback only when readback shows exactly one revision at 100
percent and all probes return their expected JSON status. Leave forward schema
migrations and the compatible reconciliation job in place. If the revision
references a retired credential, do not resurrect it: deploy the known-good
image digest as a fresh revision with the current bundles through the normal
release transaction.

## Secrets and rotation

Each Google Secret Manager secret contains one JSON object of strings mounted
as `ILLINICOVER_SECRETS_JSON`:

- `illinicover-web`: pooled `DATABASE_URL`, Django signing material, RevenueCat
  webhook and API credentials, SMTP credentials, and optional Sentry DSN;
- `illinicover-migrate`: direct `DATABASE_URL_DIRECT` and the minimum Django
  material required to load settings and prepare the schema/data.

Ordinary environment variables override matching bundle entries. Never print,
log, paste, screenshot, or commit a populated bundle.

To rotate a credential, create the replacement at its owning provider, write
the smallest affected bundle to a mode-0600 temporary file, add one new Secret
Manager version, and run the normal deployment. The deploy resolves `latest`
once and pins/readbacks its numeric version. After acceptance, inspect retained
web revisions and both jobs; destroy the old secret version and revoke its
provider credential only when no viable serving or rollback revision uses it.
For suspected exposure, rotate immediately and inspect redacted provider audit
logs.

## RevenueCat reconciliation

RevenueCat webhooks arrive at `/api/billing/revenuecat-webhook`. The server
requires both its authorization value and timestamped signature and deduplicates
the provider event ID. Repair webhook credentials and replay provider events
before reconciling the mirror.

The sole application schedule invokes `illinicover-reconcile` daily through a
dedicated OAuth service account. Its exact command is:

```bash
python server/manage.py reconcile_revenuecat --settings=config.settings.production
```

The deployed job pins the serving image digest, `illinicover-web` identity,
pooled mode, numeric web-secret version, production environment, and code SHA.
For immediate recovery, invoke that same job without copying credentials:

```bash
gcloud run jobs execute illinicover-reconcile \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --wait
```

The command refreshes every surviving account entitlement and retries pending
RevenueCat customer deletions. Compare discrepancies to RevenueCat and Apple
records; never edit the entitlement mirror to manufacture success.

## Database restore

A database restore is for confirmed data damage, not an application failure.

1. Stop writes by removing public invocation or presenting maintenance, then
   read back the service state. Record only incident time, immutable revision,
   affected tables, and owner—never rows or credentials. Preserve the damaged
   database branch.
2. Create an isolated Neon point-in-time branch immediately before the first
   bad write. Use a temporary direct credential in process memory with
   `sslmode=verify-full` and `channel_binding=require` where supported.
3. Against the known-compatible image, inspect `migrate --check --plan`, verify
   bounded invariants without exposing row data, and prove readiness. If it
   fails, discard the candidate and choose another restore point; do not repair
   the candidate by hand.
4. Create new least-privilege pooled and direct credentials on the accepted
   branch and new versions of both Secret Manager bundles. Run the normal
   deployment so migrate, canonical bootstrap, candidate probes, promotion, and
   stable readback remain one transaction.
5. Restore public invocation, replay/reconcile RevenueCat, and exercise the
   real-backend runtime contract. Retain the damaged branch until acceptance.
6. Revoke obsolete database credentials and secret versions and delete only
   the explicitly selected branch after provider readback confirms the new
   authority.

If a restore candidate is wrong, contain writes again and select a new isolated
point. Database restore and Cloud Run traffic rollback are separate decisions.
