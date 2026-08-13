# Google Cloud release preflight — 2026-08-12

This is a historical read-only receipt captured at `2026-08-12T17:27:12Z`. It
records state before the first Cloud Build or Cloud Run cutover; it is not a
current deployment receipt. Later repository configuration and live receipts
supersede its zero-resource facts and max-instance expectation.

## Confirmed project and footprint

- project: `illinicover` (`1068900473446`), billing enabled on
  `014E0F-0F5CA5-C55A37`;
- region: Cloud Run and Artifact Registry `us-east5`, Scheduler `us-east4`;
- Cloud Run services: 0;
- Cloud Run jobs: 0;
- Scheduler jobs: 0;
- Artifact Registry image versions: 0;
- provider-reported repository cost size: 0 bytes;
- Artifact Registry vulnerability scanning: disabled;
- user-managed service-account keys: 0 across web, migrate, and jobs;
- enabled secret versions: one each for web, migrate, and jobs.

The Artifact Registry repository already has the checked-in seven-day cleanup
and keep-two-newest policies. Retained-image count alone is not a cost receipt;
the deploy script now checks the provider's repository `sizeBytes` before and
after a first build and stops before Cloud Run changes if the repository exceeds
0.5 GiB. Artifact Registry's allowance is billing-account-wide, so a final
zero-cost claim also requires checking other projects on that billing account.
The visible active projects currently expose no other Artifact Registry
repository, but that is not a billing export.

## Intentional pre-cutover differences

The `_Default` Cloud Logging bucket retains routed records for 30 days and does
not yet have `exclude-cloud-run-request-logs`. The deploy script installs or
updates the exact `log_id("run.googleapis.com/requests")` exclusion, then
verifies its enabled filter before building or serving anything. The final
release receipt must capture that readback.

`illinicover-jobs@illinicover.iam.gserviceaccount.com` still has project-wide
`roles/run.invoker` because no job resource exists yet. During cutover the
script first deploys the nightly job, grants the same role on that job, removes
the unconditioned project binding, and verifies both sides before migration,
bootstrap, Scheduler creation, or public web rollout.

## Immutable release and command

`scripts/release/source_revision.py` hashes the exact `.gcloudignore` upload
set. Both base images are digest-pinned. A repeated source-hash tag reuses its
existing digest; a first build resolves the tag to a digest and every Cloud Run
resource is deployed by that digest. Image and `CODE_REVISION` are read back
before job execution and web probing.

The predicted deterministic origin is
`https://illinicover-api-1068900473446.us-east5.run.app`. Immediately before
cutover, from the repository root:

```bash
release_revision="$(python3 scripts/release/source_revision.py)"
GCP_PROJECT_ID=illinicover \
PUBLIC_API_ORIGIN=https://illinicover-api-1068900473446.us-east5.run.app \
BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS=RECEIPT_REQUIRED \
CODE_REVISION="$release_revision" \
IMAGE_TAG="$release_revision" \
ops/deployment/deploy-cloud-run.sh
```

The script configures and verifies the nightly scheduler before running
migration/bootstrap or changing public web traffic. It then requires migration
and bootstrap success before web rollout, verifies digest/revision correlation,
and probes live, ready, API status, privacy, and Django Admin static content.
Nightly itself is configured but not executed during release.

## Required cutover receipts

- Cloud Build success and final image digest;
- provider-reported Artifact Registry size below 0.5 GiB and billing-account
  usage within the shared allowance;
- enabled request-log exclusion with the exact filter above;
- resource-scoped nightly invoker present and project-wide invoker absent;
- successful migration and bootstrap executions using the same digest;
- web service min 0, max 3, request CPU, 1 vCPU, 512 MiB, no startup boost;
- Scheduler schedule, target, OAuth identity, and job-scoped IAM readback;
- direct `run.app` XFF smoke showing attacker-controlled prefixes do not alter
  the keyed network identity, without retaining raw headers;
- live endpoint and Admin-static probe results.

No Cloud Build, Cloud Run, Scheduler, IAM, provider, or logging mutation was
performed while capturing this preflight.

## Current read-only rebase — 2026-08-12T22:51:24Z

The historical zero-resource state above has been superseded. A metadata-only
readback, with no provider mutation, found:

- `illinicover-api` revision `illinicover-api-00003-rs9` receives 100 percent
  of traffic, references backend digest `e3963331…0626`, and is pooled, but its
  live environment does not yet set `DEPLOYMENT_ENVIRONMENT`;
- bootstrap, migrate, and nightly jobs reference that same digest; the
  repository-defined refresh job is not yet live. Bootstrap and nightly remain
  direct rather than the current repository's pooled setting, and all three
  live jobs omit `DEPLOYMENT_ENVIRONMENT`;
- `illinicover-nightly` Scheduler is enabled at `17 10 * * *`;
- the exact Cloud Run infrastructure request-log exclusion is enabled and its
  `log_id("run.googleapis.com/requests")` filter passed repository verification;
- Artifact Registry reports `sizeBytes=683539713`, above both the repository's
  conservative 500,000,000-byte release ceiling and the 0.5 GiB
  (536,870,912-byte) billing-account free allowance.

The Artifact Registry package contains one live digest and one newer unserved
OCI index:

| Digest | Tag | Created/updated (UTC) | Provider image size | Live reference |
| --- | --- | --- | ---: | --- |
| `e3963331…0626` | `src-b21a63…356b` | 18:26:18 | 205,150,943 | serving service and all three live jobs |
| `702a336d…bc0f` | `src-30b4da…6747` | 18:58:18 | OCI index | none |
| `0674b7dd…79be` | none | 18:58:17 | 205,153,585 | unserved child of `702a336d…bc0f` |
| `f8ac372a…0527` | none | 18:58:17 | 1,524 | unserved attestation child of `702a336d…bc0f` |

Older service revisions `00001` and `00002` name digests that Artifact Registry
already reports absent, so they are not viable rollback images. The safest
cleanup candidate is the exact unserved `702a336d…bc0f` index with its tag and
children, followed by repository-size and absence readback. No deletion was
performed for this receipt.

This is a hard stop for another build or deploy. Current source automation also
fails closed above the ceiling. Artifact Registry storage is billed hourly
above the 0.5 GiB-month/account allowance; this receipt proves immediate charge
exposure, not that an invoice has posted. Billing-account-wide Artifact Registry
usage and posted cost could not be read because the billing/budget API is not
enabled for this project, so the zero-charge claim remains unproven until the
unserved image is removed and both repository and billing usage are read back.
The next accepted release must additionally prove pooled bootstrap/refresh/
nightly modes and exact production environment readback before claiming job or
Sentry/log correlation. Scheduler is currently enabled against the stale
direct-mode nightly job.

## Cost containment — 2026-08-13T00:45:29Z

After explicit operator authorization, the exact unserved OCI index
`702a336d…bc0f`, its `src-30b4da…6747` tag, image child
`0674b7dd…79be`, and attestation child `f8ac372a…0527` were deleted. A
pre-delete readback found no service, revision, or job reference to any of the
four targets. The serving digest `e3963331…0626`, revision
`illinicover-api-00003-rs9`, and all three deployed jobs remained intact.
Artifact Registry subsequently listed only the serving image.

The repository `sizeBytes` counter remained 683,534,761 immediately after the
deletion. Artifact Registry retains unreferenced layers until its asynchronous
daily reclamation pass, so no Cloud Build or deploy is permitted until a later
readback falls below the checked-in 500,000,000-byte ceiling. This delayed
counter is not evidence that the deleted image is still addressable.

The stale `illinicover-nightly` Scheduler job in `us-east4` was paused and read
back as `PAUSED`; no Cloud Run job execution had occurred. It remains paused
until an accepted release deploys and verifies pooled normal jobs, the refresh
job, and production environment metadata.

The auto-created `gs://illinicover_cloudbuild` source bucket contained four
completed-build upload archives totaling 5,614,639 bytes. Those exact objects
were deleted, including their default seven-day soft-deleted generations. The
bucket now reports zero bytes, soft delete is disabled, and the checked-in
one-day lifecycle at `ops/deployment/cloudbuild-source-lifecycle.json` is
active. Build metadata was retained; no running service data, database data,
secrets, or serving image was removed.

## Secret Manager cost containment — 2026-08-13T01:13:27Z

A metadata-only reference map first verified that the production service and
all deployed jobs used the `latest` alias for their owning bundle and that no
disabled version was named explicitly. The following obsolete disabled
versions were then destroyed exactly:

| Secret | Destroyed versions | Retained enabled version |
| --- | --- | --- |
| `illinicover-web` | 3, 4, 5, 6 | 7 |
| `illinicover-migrate` | 2, 3, 4 | 5 |
| `illinicover-jobs` | 3, 4, 5 | 6 |

The post-cleanup inventory is three billable active versions: web 7, migrate
5, and jobs 6, all `ENABLED`; no production bundle has a `DISABLED` version.
Google Secret Manager counts both enabled and disabled versions toward billed
active-version usage. Its current billing-account allowance is six active
versions, so the former 13-version inventory exceeded that allowance even
though ten versions were disabled. Destroyed versions are not active billable
versions. The allowance is billing-account-wide, and this project-only
metadata receipt is not a billing export for other projects.

The source lifecycle now prevents recurrence. Production and preview releases
inventory metadata before any build or preview-data mutation, cap a settled
inventory at six, allow at most two serialized candidate slots, pin numeric
versions into Cloud Run, and retire predecessors only after exact accepted
resource/readiness readback. Retirement disables and verifies a predecessor
before destroying it, then verifies the project returned to six or fewer
active versions with no disabled versions. A failed rotation retains its
accepted predecessor and blocks another rotation until explicit reconciliation.
The workflows also require the numeric
`GCP_OTHER_PROJECT_ACTIVE_SECRET_VERSIONS` receipt and include it in both
steady-state and candidate headroom; an absent billing-account receipt fails
closed.

The current cost-sensitive provider state at this receipt boundary is:

- Artifact Registry lists only serving digest `e3963331…0626`; its repository
  counter remains 683,534,761 bytes until asynchronous unreferenced-layer
  reclamation, so Cloud Build and deployment remain stopped above the
  500,000,000-byte repository guard;
- the Cloud Build staging bucket is empty, soft delete is disabled, and its
  one-day deletion lifecycle is active;
- the nightly Scheduler remains `PAUSED`, and no Cloud Run job execution had
  occurred during containment;
- Secret Manager has the three active production versions above. The two
  preview bundles and Neon preview API key are not to be created until the WIF,
  billing-account inventory, and six-version headroom checks pass;
- the Billing/Budget API was not enabled merely for inspection. Posted spend
  and billing-account-wide allowance consumption therefore remain unproven by
  this project receipt.

No secret payload was printed or copied while creating this inventory and
cleanup receipt.

## Preview bootstrap — 2026-08-13T01:30:15Z

The optional preview boundary is now provisioned without copying production
data:

- Neon Free project `IlliniCover Dev` (`round-violet-50260185`) was created in
  AWS US East 2 on PostgreSQL 18. Its synthetic baseline is the default
  `production` branch (`br-shiny-field-ayr7xa1k`), database `neondb`, and role
  `neondb_owner`.
- A disposable branch was created from that baseline with a 15-minute
  expiration, read back with its exact ID/name/expiry, deleted by exact branch
  ID, and confirmed absent. No production project or branch was read or cloned.
- The Neon automation credential was copied once into Secret Manager as
  `neon-preview-api-key` version 1; the temporary local transfer and browser
  clipboard were cleared. Its payload was not logged or stored in GitHub.
- `illinicover-preview-web` and `illinicover-preview-migrate` version 1 contain
  only the same generated preview-only Django key. The workflow replaces the
  appropriate URL in each candidate bundle after creating/resetting an expiring
  Neon branch. No production URL or application secret is present.
- Preview deploy may read the Neon credential and the two preview bundles and
  may manage versions only on the two bundles. Preview web and migration
  identities may read only their own bundle. No preview identity appears on a
  production-secret IAM policy.
- The complete billing-account receipt remains zero active versions outside
  this sole linked project. Live inventory is therefore exactly six active
  versions: three production bundles, the Neon API key, and two preview
  bundles. The checked-in guard independently read back `6` with no pending
  rotation.

GitHub now has the exact Neon project/parent/database/role/secret-name variables
and a distinct preview WIF provider. Provider attributes restrict production to
the `deploy.yml` workflow on `main`; preview is restricted to `preview.yml` on
`main` for pull-request or manual-dispatch events. Both bindings are keyless and
repository-scoped to `lumirth/IlliniCover-v2`.

This receipt does not claim a preview deployment: Artifact Registry still
reports 683,534,761 billed bytes while asynchronous layer reclamation is
pending, so Cloud Build and both deployment workflows remain intentionally
blocked.

The nightly trigger boundary was also separated during this bootstrap. The
paused `illinicover-nightly` Scheduler job now uses
`illinicover-scheduler@illinicover.iam.gserviceaccount.com`, and that identity
alone has resource-scoped `roles/run.invoker` on the nightly Cloud Run job.
The former jobs-runtime invoker binding was removed. The schedule, target URI,
time zone, OAuth identity, and `PAUSED` state were read back after the change;
no job execution occurred.

## Posted billing readback — 2026-08-13T01:33Z

The signed-in Cloud Billing console reports `$0.03` total usage cost for
August 1–12, 2026. The exact SKU table attributes the charge only to 0.19 GiB
of `Artifact Registry Network Internet Egress North America to North America`
(displayed as `$0.02`; the account total rounds to `$0.03`). That volume is
approximately one 205 MB container-image download to a non-Google client.
Cloud Build's 3.03 CPU-minutes/12.2 RAM-minutes, Cloud Run, Secret Manager, and
Artifact Registry storage all display `$0.00`. This is the charge that crossed
the deliberately sensitive
`IlliniCover Any Cost` `$0.01` budget and generated the budget email. The
separate `IlliniCover Cloud Run Cap` remains at `$0.00 / $0.50` with its spend
cap configured.

This corrects the earlier "posted cost unavailable" uncertainty: the billing
console now shows a real three-cent charge, but no missing free-tier switch and
no runaway Cloud Run or Cloud Build compute. Artifact Registry's storage free
tier does not cover Internet egress; same-location transfer to Cloud Run and
Cloud Build is free. Release verification therefore uses metadata-only reads
and same-region provider operations and must not pull production images to a
developer machine.
The repository/storage and build safeguards remain necessary because billing
data can arrive with delay and the registry counter is still above the
checked-in build ceiling.
