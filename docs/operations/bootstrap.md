# Operations bootstrap

This is the one-time provider checklist, not a routine deployment path. The
repository does not provision providers automatically, and no placeholder may
be copied into a live resource.

## Local and repository baseline

1. Install mise 2026.8.5 or newer, then run `mise install` and
   `mise run setup`. This starts only the local PostgreSQL service in
   `compose.yaml`, migrates it, and runs the deterministic beta bootstrap.
2. Run `scripts/ci/ops.sh` and the relevant backend/data checks.
3. Install the Renovate GitHub App and allow `renovate.json` to own dependency
   pull requests. Do not enable global automerge.

## Google Cloud and GitHub

Create the external resources listed in `IC-V2-OPS-001.md` with separate
service accounts for deploy, web, migration, normal jobs, Scheduler, preview
deploy, preview web/jobs, and preview migration. Apply least privilege per
resource; never create a user-managed service-account key.

Configure these GitHub repository or environment variables. Values containing
`REQUIRED` are invalid and workflows fail closed:

- `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ARTIFACT_REPOSITORY`;
- `GCP_OTHER_PROJECT_ACTIVE_SECRET_VERSIONS`, a current metadata-only count for
  active versions in every other project on the same billing account;
- `GCP_WORKLOAD_IDENTITY_PROVIDER`;
- `GCP_PREVIEW_WORKLOAD_IDENTITY_PROVIDER`, distinct from production;
- `GCP_DEPLOY_SERVICE_ACCOUNT`, restricted to this repository and `main`;
- `GCP_PREVIEW_DEPLOY_SERVICE_ACCOUNT`, restricted to this repository and the
  preview workflow;
- `PRODUCTION_API_ORIGIN`, `PREVIEW_API_ORIGIN`;
- `NEON_DEV_PROJECT_ID`, `NEON_PREVIEW_PARENT_BRANCH`,
  `NEON_PREVIEW_DATABASE`, `NEON_PREVIEW_ROLE`, and
  `NEON_PREVIEW_API_SECRET`.

Create separate production and preview Secret Manager entries. Production web
and normal jobs receive pooled URLs. Migration identities receive direct URLs.
Preview uses `illinicover-preview-web` (pooled URL plus preview-only app
secrets) and `illinicover-preview-migrate` (direct URL plus the minimum Django
key). Together with the three production bundles and `neon-preview-api-key`,
this stays at six active Secret Manager versions. The preview runtime cannot
read production or migration secrets.

Grant the production deploy identity metadata-only Secret Manager viewer plus
version-manager access on the three production bundles; grant the preview
deploy identity the same narrow capabilities only on the two preview bundles.
Neither identity needs `secretAccessor` for production payloads. Runtime
service accounts remain the payload accessors for their exact bundles. Google
counts both `ENABLED` and `DISABLED` versions as billable active versions, so a
disabled version is not a free archive. The accepted steady state is at most
six active versions across the billing account. A serialized rotation may
briefly use at most two candidate slots (eight project versions), but the
workflow must pin numeric versions, complete Cloud Run readback, and return to
six before another rotation. Provider billing is prorated, so even that bounded
transition is not represented as literally zero cost.

Cloud Build may create a source-staging bucket. Apply
`ops/deployment/cloudbuild-source-lifecycle.json` to that bucket and disable
soft delete there: uploaded source archives are reproducible staging objects,
not backups. The one-day lifecycle is a failsafe; a release operator MAY delete
completed-build archives immediately after the build receipt is retained.

Create the GitHub `preview` and `destructive-migration-reviewed` labels.
Protect `main` with pull requests and the stable `CI / Required` status;
require no reviewer by default. The exceptional label is governed by
`destructive-migration.md` and is never sufficient without its exact-SHA
preview and restore receipts. GitHub Actions must be enabled before treating CI
or deployment as operational evidence.

## First production release

The first accepted release uses `.github/workflows/deploy.yml` after `main`
advances. It builds the exact commit SHA, migrates by direct connection,
creates the web service private, probes it with workload identity, and only
then grants public invocation. Later releases deploy a no-traffic candidate and
retain the previous serving revision for rollback.

Run `illinicover-bootstrap` explicitly only for initial canonical data or a
documented idempotent re-bootstrap. It uses the pooled jobs role and is not a
routine deployment step. Verify that migration stays `DATABASE_MODE=direct`,
while web/bootstrap/refresh/nightly stay `DATABASE_MODE=pooled`; every job task
timeout must remain at or below 3600 seconds.

The current provider receipt closes the six-version secret inventory, project
budget readback, Neon production restore drill, and repository/workflow claim
conditions on both WIF providers. Before beta, the final committed Git SHA must
still exercise the GitHub claim and required checks, the service-account role
audit must be attached to that release, and Artifact Registry must fall below
the checked-in build ceiling. RevenueCat Test Store/Apple-sandbox purchase and
restore, complete App Store product metadata, and Apple signing/Xcode Cloud/
TestFlight configuration remain external gates.

## Safe activation order

Do not merge the first `main` release until each earlier receipt is complete:

1. Create the private GitHub repository without pushing the v2 source to
   `main`; push the exact reviewed tree to a short-lived bootstrap branch.
2. Configure the `main` ruleset, stable required check, labels, environments,
   and non-secret variables. Keep production deployment unavailable.
3. Create the production WIF pool/provider and deploy service account. Restrict
   the attribute condition to the exact owner/repository and
   `refs/heads/main`; read back the mapping, condition, and resource-scoped IAM.
4. Create the distinct preview WIF service account and restrict it to the exact
   repository and preview workflow. Prove it cannot impersonate production
   runtime identities or read production secret payloads.
5. Create the Neon development project, synthetic parent branch, preview role,
   database, 24-hour expiration behavior, and the single infrastructure API
   key secret. Do not copy production data.
6. Create the two preview bundles and read back a six-or-fewer active-version
   inventory across the billing account. Exercise a preview only after the
   Artifact Registry counter is below the checked-in build ceiling.
7. Open and pass the bootstrap pull request. Merge only after CI, WIF claim
   readback, secret inventory, Neon isolation, and provider budget receipts are
   attached. The merge is then the first authorized automatic production
   release.
