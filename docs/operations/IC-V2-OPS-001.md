# IlliniCover v2 Development, CI/CD, and Operations Specification

Status: Proposed operational baseline
Document ID: IC-V2-OPS-001
Version: 1.0
Date: August 12, 2026
Companion to: IlliniCover v2 Product and Technical Specification
Primary system: SwiftUI + Django + PostgreSQL
Deployment providers: Google Cloud Run + Neon + RevenueCat

> **Core rule:** Keep the normal path short. Put each check at the lifecycle
> stage that owns the risk. Use recovery for rare failures. Do not make every
> change pass every check.

```text
Local -> pull request -> optional preview -> main -> migrate -> deploy -> readiness check
```

## Executive summary

IlliniCover v2 uses a deliberately small delivery system:

- Local development runs Django and PostgreSQL on the developer's Mac.
- GitHub pull requests run only the checks relevant to the changed seams.
- A single reusable preview environment is available on request; it is not mandatory.
- `main` represents the production backend and deploys automatically after safe migrations.
- GitHub Actions owns backend CI/CD. Xcode Cloud owns Apple builds, signing,
  TestFlight, and App Store artifacts.
- Neon is used only for deployed preview and production databases. Normal
  local development and CI use ordinary local or ephemeral PostgreSQL.
- RevenueCat owns purchase plumbing. Google Secret Manager owns deployed runtime secrets.
- mise is the discoverable developer interface, but it remains a thin command
  runner and tool manager.
- Humans and capable agents use the same branch, PR, preview, merge,
  deployment, simulator, and rollback paths.

The lifecycle is designed for the actual scale of IlliniCover: one monorepo,
one Django backend, one production database, native clients, a small team, and
frequent agent-assisted changes. It rejects permanent staging, mandatory
previews, heavy Git hooks, Neon-backed CI, a queue system, and
infrastructure-as-code machinery until those tools solve a demonstrated
problem.

## 0. How to use this specification

This document defines the development and operating lifecycle for IlliniCover
v2. It is normative for repository structure, environment boundaries, CI/CD,
provider configuration, testing, release, and recovery. The product
specification remains authoritative for product behavior and data semantics.

### 0.1 Normative terms

| Term | Meaning |
| --- | --- |
| MUST / MUST NOT | Required for the baseline. |
| SHOULD / SHOULD NOT | Strong default. A deviation needs a recorded reason. |
| MAY | Optional. |
| Deferred | Do not build it until the stated adoption trigger occurs. |

### 0.2 Adoption sequence

Before the first production backend deploy:

- Local Django and PostgreSQL.
- mise task interface.
- Pull-request rules on `main`.
- Path-sensitive backend CI.
- Cloud Run production service.
- Neon production project.
- Google Secret Manager.
- Automatic migration job.
- Readiness smoke check.

Before internal iOS beta:

- `IlliniCover.dev` bundle identity.
- Shared preview service.
- Neon development project and expiring preview branches.
- Canonical API fixtures.
- Fixture-backed UI tests.
- RevenueCat Test Store.
- Xcode Cloud verification workflow.
- TestFlight workflow.

Before public launch:

- Tested recovery runbooks.
- RevenueCat production products and webhook reconciliation.
- Dependency automation.
- Error monitoring and actionable alerts.
- Tested database restore procedure.
- App Store release procedure.

Only after a demonstrated need:

- Feature-flag platform.
- Redis or Celery.
- OpenTofu or Terraform.
- Per-PR preview fleet.
- Permanent staging.
- Merge queue.
- Multiple production services.

### 0.3 Decision summary

| Decision | Baseline |
| --- | --- |
| Production branch | `main`. A merge starts the backend production deploy. |
| Change boundary | A pull request and relevant CI checks. No approval is required by default. |
| Preview | Optional. Request with a `preview` label. Manual workflow dispatch is the fallback. |
| Environments | Local, one reusable preview, and production. No permanent staging. |
| Local database | Local PostgreSQL. Local work does not depend on Neon or Cloud Run. |
| CI database | Ephemeral PostgreSQL in GitHub Actions. Neon is not used for normal CI. |
| Backend CI/CD | GitHub Actions with Google Workload Identity Federation. |
| Apple CI/CD | Xcode Cloud for Apple builds, signing, tests, TestFlight, and App Store artifacts. |
| Developer interface | mise. Atomic tasks only. GitHub Actions owns CI policy. |
| Git hooks | No mandatory hooks. |
| Migrations | Automatic for safe migrations. A small exceptional path for destructive changes. |
| Testing data | Backend-defined scenarios export canonical API fixtures. |
| Simulator | Dedicated reusable simulator. Xcode MCP for exploration. XCTest and `simctl` for repeatability. |
| Billing tests | RevenueCat Test Store in development. Apple sandbox in TestFlight. Testers are not charged. |
| Dependencies | Renovate, grouped and low-noise. |
| Infrastructure definition | Recurring config in the repo. One-time provider bootstrap in concise runbooks. No IaC engine yet. |
| Agents and humans | Same branch, PR, preview, merge, deploy, and rollback path. |

## 1. Purpose and scope

This specification defines how IlliniCover v2 is developed, tested, previewed,
deployed, monitored, and recovered. It also defines how the repository
represents these flows.

- **OPS-001** The normal development path MUST remain short enough for frequent commits and small pull requests.
- **OPS-002** Every automated check MUST have one clear owner and one clear failure meaning.
- **OPS-003** The lifecycle MUST be suitable for a small project with human and agent contributors. It MUST NOT assume a large release organization.
- **OPS-004** Provider-specific services MUST remain replaceable at the infrastructure boundary. Application code MUST depend on PostgreSQL and HTTP semantics, not provider-specific data APIs.
- **OPS-005** The repository MUST explain the recurring lifecycle. Provider dashboards MAY contain one-time configuration that cannot be represented economically in the repository.

## 2. Governing principles

| Principle | Operational meaning |
| --- | --- |
| One production branch. | `main` is production for the backend. |
| Optional preview. | Preview is a capability. It is not a mandatory stage. |
| Cloud-independent local work. | Local development uses local Django and local PostgreSQL. |
| Relevant checks only. | The blast radius of a change determines the checks. |
| Fast Git. | Git hooks do not run a miniature CI system. |
| Recovery over ritual. | Use revision rollback, model rollback, and database restore. Do not add preventive ceremony to every change. |
| One owner per seam. | GitHub owns backend CI/CD. Xcode Cloud owns Apple CI/CD. Django owns migrations. Neon owns hosted PostgreSQL. RevenueCat owns commerce plumbing. |
| Human-agent parity. | A capable agent MAY merge and deploy through the same guarded path as a human. |
| Automate recurring actions. | Encode tasks that occur repeatedly. Document one-time provider bootstrap. |
| Free tier by construction. | Use scale-to-zero, local CI databases, optional previews, and cleanup policies. Do not poll providers continuously. |

**Anti-bureaucracy rule.** A new workflow, job, environment, or gate must
remove more repeated work or risk than it adds.

## 3. Delivery lifecycle

```text
Local
  mise + local Django + local PostgreSQL
    |
Pull request
  relevant CI only; no required human approval
    +-- optional preview
    |     preview label or manual dispatch
    |     shared Cloud Run preview + expiring Neon dev branch
    +-- no preview
          normal path for most changes
    |
main
  always releasable; backend deployment starts
    |
Production
  migrate -> deploy -> readiness check -> rollback if needed
```

Normal changes use local work, a pull request, relevant CI, and an automatic
production deploy. Preview is optional.

- **LIFE-001** A contributor MUST work on a short-lived branch.
- **LIFE-002** A pull request MUST target `main` before the change can enter production.
- **LIFE-003** The pull request MUST pass only the checks that own the affected seams.
- **LIFE-004** A contributor MAY request the shared preview environment when local and CI evidence is not sufficient.
- **LIFE-005** A merge to `main` MUST start the production backend deployment automatically.
- **LIFE-006** The iOS binary MUST use a separate release flow. A backend merge MUST NOT automatically create a TestFlight build.
- **LIFE-007** A cover-model code change MUST NOT automatically promote a challenger model. Model promotion is an explicit operation.

## 4. Environment model

```text
LOCAL
  IlliniCover.dev
  local Django
  local PostgreSQL
  RevenueCat Test Store
  .env.local
  no production access

PREVIEW
  IlliniCover.dev
  shared Cloud Run preview
  expiring Neon development branch
  RevenueCat Test Store
  preview-only Secret Manager values
  no ability to read production secrets

PRODUCTION
  IlliniCover bundle identity
  Cloud Run production
  Neon production project
  RevenueCat production configuration
  Apple sandbox purchases in TestFlight
  production Secret Manager values
```

Local, preview, and production use separate configuration, identity, and data boundaries.

### 4.1 Environment definitions

| Context | Application | Database | Billing | Use |
| --- | --- | --- | --- | --- |
| SwiftUI Preview | Fixture transport | None | Fixture or Test Store | View design and isolated states. |
| Local | `IlliniCover.dev` -> local Django | Local PostgreSQL | RevenueCat Test Store | Daily development. |
| Preview | `IlliniCover.dev` -> shared Cloud Run preview | Expiring Neon dev branch | RevenueCat Test Store | Deployed integration checks for one active PR or branch. |
| Production | IlliniCover -> Cloud Run production | Neon production | RevenueCat production; Apple sandbox in TestFlight | Real backend and released clients. |

- **ENV-001** The baseline MUST have local, preview, and production contexts. It MUST NOT have a permanent staging environment.
- **ENV-002** The preview environment MUST use synthetic or versioned project data. It MUST NOT copy production user reports, accounts, precise locations, or billing state.
- **ENV-003** Preview and production MUST use different Neon projects or equivalent hard data boundaries.
- **ENV-004** Preview and production Cloud Run identities MUST have separate Secret Manager access.
- **ENV-005** A preview service MUST be unable to read production database and RevenueCat server secrets.
- **ENV-006** TestFlight is a distribution channel, not a fourth backend environment. The TestFlight build SHOULD use the production backend and Apple sandbox purchases.
- **ENV-007** No ordinary Debug control MUST allow a developer to redirect `IlliniCover.dev` to production.

## 5. Repository and branch policy

- **GIT-001** `main` MUST represent the backend production state.
- **GIT-002** GitHub MUST require a pull request before a change enters `main`.
- **GIT-003** The `main` ruleset MUST require relevant status checks. It MUST NOT require a human approval by default.
- **GIT-004** Repository owners and approved automation MAY merge a green pull request.
- **GIT-005** The `main` ruleset MAY have an emergency bypass. Routine work MUST NOT use it.
- **GIT-006** The repository MUST NOT use a permanent `develop` or release branch.
- **GIT-007** Force pushes to `main` MUST be blocked.
- **GIT-008** Commit-message formats and signed commits MUST NOT be required initially.
- **GIT-009** Squash merge SHOULD be the default for small feature branches. A different merge method MAY be used when preserving commit structure has clear value.
- **GIT-010** No mandatory Git hook MUST run tests, formatting, type checks, migration checks, or API checks.
- **GIT-011** Secret scanning and push protection SHOULD be enabled where the repository plan supports them. This does not justify a bespoke hook framework.

## 6. Developer interface and local setup

### 6.1 mise is the front door

The root mise configuration defines tool versions, local environment defaults,
and discoverable tasks. mise replaces a separate Justfile or Taskfile.

- **DEV-001** The repository MUST have one root `mise.toml` with monorepo mode enabled.
- **DEV-002** mise MUST own tool versions and atomic developer operations.
- **DEV-003** GitHub Actions and Xcode Cloud MUST own policy. A task named `ci-all` MUST NOT hide the full CI policy.
- **DEV-004** A new clone SHOULD become locally usable with `mise install` followed by `mise run setup`.
- **DEV-005** A task that grows into substantial logic MUST move to a Django management command, Python script, or provider workflow. The mise task remains a thin delegate.

### 6.2 Local topology

```text
IlliniCover.dev (Simulator)
  |
Django on localhost
  |
PostgreSQL in Docker Compose
```

- **DEV-006** Django SHOULD run natively through uv. Only PostgreSQL needs a local container initially.
- **DEV-007** The local database MUST be disposable. `mise run db:reset` MUST recreate, migrate, and seed only the local database.
- **DEV-008** Local email-code development SHOULD use the Django console email backend. A local mail catcher MAY be added when actual email rendering needs inspection.
- **DEV-009** Local development MUST NOT require a Neon API key, GCP credential, production database credential, or RevenueCat server secret.
- **DEV-010** The repository MUST include `.env.example`. Local values MUST live in a gitignored `.env.local` or equivalent mise-local configuration.

### 6.3 Toolchain selection

- **DEV-011** uv MUST own Python dependency resolution and the Python lock file.
- **DEV-012** Xcode remains an Apple-managed tool. mise MAY set `DEVELOPER_DIR` for tasks, but it MUST NOT attempt to install or emulate Xcode.
- **DEV-013** A developer who uses Xcode beta SHOULD set `DEVELOPER_DIR` in a gitignored local mise file. The project MUST NOT change the Mac-wide `xcode-select` value as part of normal tasks.
- **DEV-014** The authoritative Xcode Cloud workflow MUST pin an explicit Xcode version. A beta compatibility workflow MAY be non-blocking until the beta becomes the release toolchain.

## 7. Configuration and secrets

```text
GitHub Actions
  OIDC token only; no production application-secret values
    |
Google Workload Identity Federation
  short-lived deployment authority scoped to this repository
    +--> Artifact Registry
    |      immutable image tagged with the Git commit SHA
    +--> Cloud Run service and jobs
           read only the secrets granted to their service identities
             |
           Neon + RevenueCat
             remain behind explicit runtime and webhook boundaries

Google Secret Manager
  separate preview and production secret sets
    |
Cloud Run service and jobs
```

GitHub receives short-lived deployment authority. Runtime secrets remain in
Google Secret Manager.

### 7.1 Configuration classes

| Class | Examples | Storage |
| --- | --- | --- |
| Public configuration | API URL, environment name, service-night cutoff, log level | Repository or Cloud Run configuration. |
| Local development secret | Disposable local key or test credential | `.env.local`. Never a production value. |
| Preview runtime secret | Preview DB URLs, preview Django key, RevenueCat test webhook values | Google Secret Manager. Preview service identity only. |
| Production runtime secret | Production DB URLs, Django key, email provider key, RevenueCat webhook secret | Google Secret Manager. Production service identities only. |
| Deployment authority | Permission to deploy Cloud Run and push images | GitHub OIDC -> Google Workload Identity Federation. No long-lived key. |

- **SEC-001** GitHub Actions MUST use Google Workload Identity Federation. It MUST NOT store a long-lived GCP service-account key.
- **SEC-002** GitHub Actions MUST NOT store production application secret values.
- **SEC-003** A workflow MAY use its short-lived GCP identity to read the minimum infrastructure credential required for that workflow, such as the Neon preview API key.
- **SEC-004** Cloud Run production and preview MUST use separate user-managed service accounts.
- **SEC-005** Each service account MUST have only the Secret Manager access and provider permissions that its runtime role needs.
- **SEC-006** Django MUST validate required settings during startup. A missing production setting MUST stop startup with a precise error.
- **SEC-007** Ordinary configuration MUST remain outside Secret Manager. A value is not a secret only because it is an environment variable.
- **SEC-008** The application MUST use distinct pooled and direct Neon connection strings in deployed environments.

### 7.2 Baseline secret inventory

| Environment | Secret | Consumer |
| --- | --- | --- |
| Preview | `preview-database-url` | Cloud Run preview service and scheduled preview operations. |
| Preview | `preview-database-direct-url` | Preview migration job only. |
| Preview | `preview-django-secret-key` | Preview Django service/jobs. |
| Preview | `preview-revenuecat-webhook-secret` | Preview webhook path, if enabled. |
| Production | `prod-database-url` | Production web and scheduled jobs. |
| Production | `prod-database-direct-url` | Production migration job only. |
| Production | `prod-django-secret-key` | Production Django service/jobs. |
| Production | `prod-email-provider-key` | Production Django service. |
| Production | `prod-revenuecat-webhook-secret` | Production webhook handler. |
| Infrastructure | `neon-preview-api-key` | Preview GitHub workflow through WIF. |

## 8. Canonical test data and mocks

```text
Django scenario builder
  creates valid domain state in real models
    |
Real API serializer
  uses the production response path
    |
Checked-in API fixture
  canonical JSON example reviewed as a diff
    +--> SwiftUI previews + fixture UI tests
    |      fast, deterministic, offline
    +--> Small full-stack UI suite
           Simulator -> generated client -> Django -> PostgreSQL
```

Backend scenarios emit the fixtures used by previews and fast iOS tests. A
small real-stack suite detects drift.

- **FIX-001** The backend MUST own canonical product scenarios.
- **FIX-002** A scenario builder MUST create valid state through Django models and domain services.
- **FIX-003** Fixture export MUST call the real API serialization path. A Swift file MUST NOT manually recreate the expected server payload.
- **FIX-004** Canonical API fixtures MUST be checked into `api/fixtures` and reviewed as normal diffs.
- **FIX-005** CI MUST regenerate canonical fixtures and fail when the checked-in fixture set is stale.
- **FIX-006** SwiftUI previews and fixture UI tests MUST use the same fixture transport and generated OpenAPI types.
- **FIX-007** The fixture set MUST include normal, sparse, conflicting, stale, error, empty, premium, and offline-submission states.
- **FIX-008** A small full-stack iOS suite MUST use the generated client against real Django and real PostgreSQL. It exists to detect contract and behavior drift.
- **FIX-009** Normal preview and CI data MUST be synthetic. Production user data MUST NOT be copied into test fixtures.

## 9. Test strategy and ownership

### 9.1 Test classes

| Owner | Tests | Normal trigger |
| --- | --- | --- |
| Pure Python/domain | Cover resolution, trust, service night, deal rules, configuration parsing | Relevant server code changes. |
| Django/PostgreSQL | Constraints, transactions, migrations, idempotency, APIs, import behavior | Relevant server/schema changes. |
| Model evaluation | Chronological folds, calibration, interval coverage, nowcast ablations, challenger comparison | Model/data changes; full run nightly or manual. |
| Swift unit/client | View models, GRDB cache/outbox, generated client wrappers | Relevant iOS changes. |
| Fixture UI | Critical screens and flows with canonical fixtures | Relevant UI/client changes. |
| Full-stack UI | A small set of client-Django-PostgreSQL seams | API + iOS seam changes; scheduled/manual broader run. |
| Provider integration | RevenueCat sandbox, Cloud Run config, Neon preview lifecycle | Only when provider-facing code/config changes. |
| Deploy smoke | Process startup, DB reachability, migration compatibility | Every production backend deploy. |

- **TST-001** Tests MUST protect product behavior, data integrity, and external seams.
- **TST-002** Tests MUST NOT exist only to preserve directory layering, pass-through wrappers, route metadata, cache-key tuples, exact workflow strings, or documentation prose.
- **TST-003** The repository MUST NOT have a global coverage percentage veto.
- **TST-004** Critical cover, trust, identity, billing, and deletion code MAY have targeted coverage or mutation-testing requirements.
- **TST-005** Normal PR CI MUST use small deterministic model fixtures. The complete historical backtest MUST run only when model/data changes require it or on a scheduled/manual workflow.
- **TST-006** A deployment smoke check MUST NOT become a second integration suite.

## 10. GitHub Actions CI

### 10.1 Workflow files

```text
.github/workflows/
  ci.yml
  preview.yml
  deploy.yml
  model-evaluation.yml
```

- **CI-001** `ci.yml` MUST run on pull requests to `main`.
- **CI-002** CI MUST use path filters or a change-classification step so unrelated jobs do not run.
- **CI-003** Backend tests MUST use an ephemeral PostgreSQL service container. Normal CI MUST NOT use Neon.
- **CI-004** Superseded CI runs on the same branch SHOULD be canceled.
- **CI-005** CI jobs SHOULD call atomic mise tasks where this improves local reproducibility. The workflow file MUST still show which checks are required.
- **CI-006** The required status checks on `main` MUST be stable names. Optional, nightly, and manual jobs MUST NOT block unrelated merges.
- **CI-007** CI MUST retain useful failure artifacts, such as an `xcresult` bundle, generated fixture diff, migration log, or test report. It MUST NOT retain routine successful artifacts without a use.

### 10.2 Path-sensitive baseline

| Changed paths | Required work |
| --- | --- |
| `server/**` | Ruff, Django-aware mypy with django-stubs, pytest, PostgreSQL integration, migration check. |
| `server/**/migrations/**` | Fresh migration test, upgrade test, migration-risk classification. |
| `api/openapi.json` or API schemas | OpenAPI generation/diff and iOS generated-client compile. |
| `api/fixtures/**` or scenario builders | Fixture regeneration/diff and fixture consumer tests. |
| `data/**` or model code | Import validation and relevant model evaluation. |
| `ios/**` | Xcode Cloud Verify workflow and relevant Swift tests. |
| `ios/**` UI areas | Fixture UI test plan when the touched surface warrants it. |
| `ops/**` or `.github/**` | Workflow/config syntax and Cloud Run YAML dry-run where possible. |
| `docs/**` only | No app build or database startup unless the document is executable configuration. |

### 10.3 Main ruleset

- **CI-008** The `main` ruleset MUST require a pull request and relevant required status checks.
- **CI-009** The ruleset MUST NOT require a reviewer by default.
- **CI-010** Agents and humans with merge permission MAY merge when the same checks pass.
- **CI-011** The ruleset MAY allow an emergency bypass actor. Bypass actions MUST remain visible in GitHub history and audit logs.

## 11. Preview lifecycle

- **PRE-001** The normal preview trigger MUST be the `preview` pull-request label.
- **PRE-002** A manual `workflow_dispatch` trigger MUST be available as an escape hatch for an arbitrary branch or commit.
- **PRE-003** The project MUST have one reusable Cloud Run preview service initially.
- **PRE-004** The preview workflow MUST use a fixed concurrency group so two deployments cannot overwrite the shared preview simultaneously.
- **PRE-005** The workflow MUST create or reset an isolated branch in the Neon development project.
- **PRE-006** The Neon preview branch MUST have an automatic expiration time. Twenty-four hours is the baseline unless the PR needs more time.
- **PRE-007** The preview database MUST receive deterministic development seed data and only the versioned historical subset required by the change.
- **PRE-008** The workflow MUST run preview migrations before it deploys the preview service.
- **PRE-009** The workflow SHOULD post the preview URL and database-branch identity on the pull request.
- **PRE-010** Removing the label, closing the PR, or merging the PR SHOULD clean the preview state. Neon branch expiration is the cleanup failsafe.
- **PRE-011** Preview MUST NOT be mandatory for ordinary changes.

Use preview for seams, not comfort. Typical reasons are authentication changes,
RevenueCat changes, a cross-client API change, a risky migration, Cloud Run
configuration, or a complex cover resolver change.

## 12. Production deployment

### 12.1 Deploy pipeline

```text
merge to main
  - authenticate to Google Cloud with OIDC
  - build one immutable image
  - push image tagged with the Git commit SHA
  - update and execute migration Cloud Run Job
  - deploy the same image to the Cloud Run service
  - run one readiness smoke check
  - success, or restore traffic to the previous revision
```

- **DEP-001** `deploy.yml` MUST run when `main` advances.
- **DEP-002** The image MUST be immutable and tagged with the Git commit SHA.
- **DEP-003** The production migration job and web service MUST use the same image.
- **DEP-004** The migration job MUST finish successfully before the new web revision receives production traffic.
- **DEP-005** The post-deploy smoke check MUST verify process readiness, database reachability, and migration compatibility. It MUST NOT run purchases, model backtests, or a broad API suite.
- **DEP-006** The workflow MUST record the previous serving revision before deployment.
- **DEP-007** If the new revision fails readiness, the workflow MUST retain or restore the previous serving revision.
- **DEP-008** A routine production deployment MUST NOT require a manual approval.
- **DEP-009** There MUST NOT be a second supported routine production deployment path hidden behind a local mise task.

### 12.2 Mobile compatibility

- **DEP-010** Backend releases MUST be compatible with mobile clients that are already installed.
- **DEP-011** Within `/api/v2`, ordinary changes SHOULD be additive.
- **DEP-012** The server MUST NOT require an atomic backend and App Store release.
- **DEP-013** A field or endpoint MAY be removed only after the supported mobile versions no longer use it or after a new API version is available.

## 13. Database migration policy

### 13.1 Normal migrations

- **MIG-001** Django migrations MUST own schema evolution.
- **MIG-002** CI MUST fail when model changes require a migration that is not checked in.
- **MIG-003** CI MUST apply the full migration chain to a fresh PostgreSQL database.
- **MIG-004** CI SHOULD test the supported upgrade path from the most recent release baseline when a migration changes existing tables.
- **MIG-005** Safe migrations MUST run automatically in the production deploy pipeline.
- **MIG-006** The application MUST use expand -> use -> contract for incompatible schema changes.

### 13.2 Destructive migration exception

A destructive migration is one that can remove data, reinterpret stored
evidence, or make the previous application revision incompatible. Examples
include `RemoveField`, `DeleteModel`, destructive `RunSQL`, or a non-reversible
data rewrite.

- **MIG-007** CI MUST identify a likely destructive migration and mark the pull request as requiring the exceptional path.
- **MIG-008** A destructive migration SHOULD be redesigned as expand -> data migration -> code switch -> later contract whenever possible.
- **MIG-009** A remaining destructive migration MUST be tested in the preview environment before merge.
- **MIG-010** Before deployment, the operator or workflow MUST confirm that Neon point-in-time recovery or a current manual snapshot can restore the pre-change state.
- **MIG-011** The exceptional path MUST be represented by one explicit pull-request marker and one concise runbook. It MUST NOT become a second general deployment system.
- **MIG-012** The deploy pipeline MUST NOT automatically reverse a production database migration after an application rollback.
- **MIG-013** Large data migrations MUST be idempotent, resumable, and observable. They SHOULD run as a separate management command rather than inside a long schema transaction.

## 14. Cloud Run runtime

### 14.1 Baseline resources

| Resource | Baseline |
| --- | --- |
| `illinicover-prod` | Public Cloud Run service in `us-east5`. Request-based billing. Minimum instances 0. Maximum instances 3. |
| `illinicover-preview` | Public preview service in `us-east5`. Minimum instances 0. Maximum instances 1. |
| `illinicover-migrate` | Private Cloud Run Job. Same image. Direct Neon connection. Command: `python manage.py migrate --noinput`. |
| `illinicover-refresh` | Private Cloud Run Job for context refresh work. |
| `illinicover-nightly` | Private Cloud Run Job for model training, deal refresh, cleanup, and reconciliation. |
| Artifact Registry | Stores immutable backend images. Cleanup policy removes old unreferenced images. |

- **RUN-001** Cloud Run services MUST use request-based billing and minimum instances 0 until measured latency justifies an always-warm instance.
- **RUN-002** Production MUST start with a service-level maximum of 3 instances. Preview MUST start with a maximum of 1.
- **RUN-003** Maximum instances MAY change after database connection and traffic measurements.
- **RUN-004** The runtime service MUST use a user-managed service account. It MUST NOT use the broad default Compute Engine service account.
- **RUN-005** The container filesystem MUST be treated as disposable.
- **RUN-006** The web container MUST listen on the Cloud Run `PORT` value.
- **RUN-007** The API service MAY be public. Django remains responsible for application authentication and authorization.
- **RUN-008** Jobs MUST be private and executable only by the deployment or scheduler identities.

### 14.2 Health and readiness

- **RUN-009** A liveness or startup endpoint MUST check the process only. It MUST NOT query Neon on a recurring probe.
- **RUN-010** The deploy smoke check MAY call a separate deep readiness endpoint that performs one database query.
- **RUN-011** An external uptime monitor MUST NOT call the deep database readiness endpoint frequently enough to defeat Neon scale-to-zero.

### 14.3 Image retention

- **RUN-012** Artifact Registry MUST have a cleanup policy for untagged and old preview images.
- **RUN-013** The cleanup policy MUST retain all images used by serving Cloud Run revisions and a small rollback window of recent production images.

## 15. Neon operations and Free-plan hygiene

### 15.1 Project topology

- **NEON-001** The baseline MUST use two Neon projects: `illinicover-prod` and `illinicover-dev`.
- **NEON-002** Production data MUST live only in `illinicover-prod`.
- **NEON-003** The dev project MUST contain the preview baseline branch and expiring preview branches.
- **NEON-004** Local development and normal CI MUST NOT use Neon.

### 15.2 Connections

- **NEON-005** Cloud Run web and normal scheduled jobs MUST use the pooled Neon connection string.
- **NEON-006** Django migrations MUST use the direct Neon connection string.
- **NEON-007** The initial Django connection policy SHOULD use short-lived application connections and rely on Neon pooling. Persistent connection tuning requires measurement.
- **NEON-008** Cloud Run maximum-instance limits MUST protect Neon from connection bursts.

### 15.3 Free-plan hygiene

- Keep scale-to-zero enabled.
- Do not run a no-op scheduler every minute.
- Do not use Neon for local work or routine CI.
- Expire preview branches automatically.
- Do not clone production user data into the dev project.
- Do not store screenshots, logs, model binaries, or build artifacts in PostgreSQL.
- Keep product-shaped API responses compact. Use ETag and the client cache to avoid repeated large reads.
- Keep Cloud Run and Neon in nearby regions. Track public network transfer.
- Do not use a database-querying uptime probe.
- Review the Neon Resources Remaining panel at least weekly during beta and monthly after usage stabilizes.

- **NEON-009** Preview branches SHOULD expire after 24 hours by default. A longer life needs an explicit reason.
- **NEON-010** The team SHOULD investigate when storage, compute, or public transfer reaches 70 percent of the monthly allowance.
- **NEON-011** At 85 percent of an allowance, the team MUST either remove waste or upgrade. The application MUST NOT distort its architecture only to remain free.
- **NEON-012** Production restore procedures MUST use Neon point-in-time recovery or snapshots. They MUST be tested before public launch.
- **NEON-013** The database schema MUST remain ordinary PostgreSQL. Neon-specific features MAY be used only at the operations boundary.

## 16. Scheduled work

Cloud Run Jobs and Cloud Scheduler execute Django management commands from the
same backend image. The baseline uses a few explicit schedules. It does not
poll a database-backed queue continuously.

| Job | Typical responsibility | Cadence principle |
| --- | --- | --- |
| `illinicover-refresh` | Refresh deterministic context sources and source health. | Run only as often as product freshness needs. Prefer nightlife hours over 24-hour polling. |
| `illinicover-nightly` | Train cover model, run challengers, refresh deal predictions, cleanup, reconcile RevenueCat. | Run after the 5:00 AM service-night boundary. |
| Manual operations | Imports, backfills, restore validation, one-off evaluation. | Manual Cloud Run Job execution. |

- **JOB-001** Scheduled work MUST use Django management commands.
- **JOB-002** Each job MUST record a job-run receipt with code revision, start time, completion time, status, and summary.
- **JOB-003** A job SHOULD use a PostgreSQL advisory lock or equivalent guard when duplicate execution would be harmful.
- **JOB-004** Schedules MUST be explicit. A high-frequency `run_due_jobs` poller MUST NOT be introduced to simulate a queue.
- **JOB-005** A failed context source MUST NOT make the cover API unavailable.
- **JOB-006** Redis and Celery are deferred until the project has queue-shaped work: many independent jobs, immediate dispatch, priority, large worker pools, or task-specific retries.

## 17. iOS identities, schemes, and signing

### 17.1 Bundle identities

- **IOS-001** The project MUST use one Xcode application target with two bundle identities.

| Identity | Use |
| --- | --- |
| `com.<owner>.IlliniCover.dev` | Local and preview development. Can be installed beside the production app. |
| `com.<owner>.IlliniCover` | TestFlight and App Store. |

- **IOS-002** The two identities MUST allow side-by-side installation on a device.
- **IOS-003** Local and Preview MUST be shared Xcode schemes that select checked-in `xcconfig` files.
- **IOS-004** The production scheme MUST use the production bundle identity and production API URL.
- **IOS-005** Debug builds MUST display a small LOCAL or PREVIEW marker. Production MUST show no environment marker.
- **IOS-006** Only the development configuration MAY allow cleartext localhost access required by local Django.

### 17.2 Signing

- **IOS-007** Xcode automatic signing SHOULD manage development signing on developer devices.
- **IOS-008** Xcode Cloud SHOULD manage distribution signing for TestFlight and App Store artifacts.
- **IOS-009** The project SHOULD avoid manually managed `.p12` certificate files and provisioning profiles unless a concrete failure requires them.
- **IOS-010** Capabilities required by both bundle identities MUST be configured for both App IDs.

### 17.3 Schemes and configuration

```text
IlliniCover Local
  bundle: IlliniCover.dev
  API: http://127.0.0.1:8000
  purchases: RevenueCat Test Store

IlliniCover Preview
  bundle: IlliniCover.dev
  API: shared Cloud Run preview URL
  purchases: RevenueCat Test Store

IlliniCover
  bundle: IlliniCover
  API: production Cloud Run URL
  purchases: real RevenueCat iOS app key
```

## 18. Simulator and agent etiquette

- **SIM-001** The project SHOULD maintain one dedicated reusable simulator named `IlliniCover Agent` or an equivalent unambiguous name.
- **SIM-002** Automation MUST address the simulator by UDID. It MUST NOT use the first device reported as booted when multiple devices can exist.
- **SIM-003** Normal test reset MUST reset the app database, actor identity, onboarding state, and fixture selection. It MUST NOT erase the full simulator unless the OS state is part of the test.
- **SIM-004** Xcode MCP SHOULD be the primary tool for exploratory agent work in Xcode 27: build, boot, launch, interact, render previews, and capture screenshots.
- **SIM-005** XCTest, `xcodebuild`, and `simctl` MUST remain the repeatable path for assertions and CI.
- **SIM-006** Isolated view work SHOULD use Preview Snapshot and canonical fixtures before a full app launch.
- **SIM-007** Flow screenshots SHOULD use the simulator framebuffer, not a macOS screenshot of the Simulator window.
- **SIM-008** Transient UI artifacts MUST go under `.artifacts/ui/<git-sha>/` and MUST be gitignored.
- **SIM-009** Failed CI UI tests SHOULD retain the `xcresult` bundle and relevant screenshot attachments.
- **SIM-010** Interactive touch coordinates MAY be used for exploration. Stable UI tests MUST use accessibility identifiers and semantic XCUI queries.
- **SIM-011** UI tests SHOULD use serial or low parallelism while the Xcode beta has known Simulator and log-streaming issues.
- **SIM-012** Agents MUST NOT use the simulator to submit synthetic reports to production.

### 18.1 Expected visual loop

```text
edit SwiftUI
  - render a Preview Snapshot
  - inspect light, dark, orientation, and text-size variants as needed
  - run IlliniCover Local on the dedicated simulator
  - exercise the real flow
  - capture a framebuffer screenshot
  - run the relevant XCTest or UI test
```

## 19. RevenueCat testing and entitlements

| Mode | Bundle identity | Backend | Purchase path | Real charge? |
| --- | --- | --- | --- | ---: |
| SwiftUI Preview | None or development | Fixtures | Fixture or RevenueCat Test Store | No |
| Local Simulator | `IlliniCover.dev` | Local Django | RevenueCat Test Store | No |
| Preview Simulator | `IlliniCover.dev` | Cloud Run preview | RevenueCat Test Store | No |
| Xcode development device build | `IlliniCover.dev` | Local or preview | Test Store or Apple sandbox | No |
| TestFlight | `IlliniCover` | Production | Apple sandbox with real RevenueCat app configuration | No |
| App Store | `IlliniCover` | Production | Apple production | Yes |

Development, preview, TestFlight, and App Store builds have explicit backend
and purchase-test behavior.

- **RC-001** An IlliniCover account UUID MUST be the RevenueCat App User ID.
- **RC-002** The App User ID MUST be non-guessable. Email MUST NOT be used as the RevenueCat identifier.
- **RC-003** A user MUST sign in before starting a premium purchase. The SDK SHOULD be configured directly with the account UUID to avoid anonymous RevenueCat identity merging.
- **RC-004** The development bundle MUST use the RevenueCat Test Store API key.
- **RC-005** A release build MUST use the real RevenueCat iOS public SDK key. CI MUST fail if a release configuration contains the Test Store key.
- **RC-006** TestFlight MUST use the production bundle, production backend, real RevenueCat app configuration, and Apple sandbox transactions. Testers MUST NOT be charged.
- **RC-007** RevenueCat sandbox testing access SHOULD be restricted to approved tester account UUIDs before broad TestFlight distribution.
- **RC-008** The backend MUST verify RevenueCat webhooks, store the event environment, process events idempotently, and mirror the premium entitlement.
- **RC-009** Production entitlements and sandbox entitlements MUST remain distinguishable in the backend.
- **RC-010** A scheduled reconciliation command MUST repair missed or delayed webhook state.
- **RC-011** Sandbox renewal timing and metadata MUST NOT be treated as production timing or pricing behavior.

## 20. Xcode Cloud and iOS release

### 20.1 Ownership split

| System | Owns |
| --- | --- |
| GitHub Actions | Backend CI, PostgreSQL integration, OpenAPI generation, preview, Cloud Run deployment, model/data workflows. |
| Xcode Cloud | Apple builds, signing, fixture UI tests, selected integration UI tests, archive, TestFlight, App Store artifact. |

- **XC-001** The project MUST configure an iOS Verify workflow in Xcode Cloud for relevant pull-request changes.
- **XC-002** The iOS Verify workflow MUST use path filters so documentation and backend-only changes do not consume Apple build time.
- **XC-003** The project SHOULD configure a separate Integration workflow for the small real-stack iOS suite. It MAY be manual or scheduled and SHOULD NOT block every PR.
- **XC-004** TestFlight distribution MUST be explicit. It SHOULD start from a manual Xcode Cloud action or a release tag.
- **XC-005** A merge to `main` MUST NOT automatically distribute a TestFlight build.
- **XC-006** App Store submission and release MUST be explicit.
- **XC-007** Xcode Cloud workflow definitions MAY remain provider-managed initially. Checked-in schemes, `xcconfig` files, test plans, and a concise workflow runbook MUST define the repository side.
- **XC-008** `ci_post_clone.sh`, `ci_pre_xcodebuild.sh`, and `ci_post_xcodebuild.sh` MUST remain thin. They MUST NOT become a shadow CI system.
- **XC-009** The workflow MUST use a checked-in shared scheme and test plan.
- **XC-010** The TestFlight workflow SHOULD perform a clean archive only when distribution requirements make it necessary.

### 20.2 Release versioning

- **XC-011** The iOS app MUST use a user-facing version and monotonically increasing build number.
- **XC-012** Backend deployments MUST identify themselves by Git commit SHA and Cloud Run revision. They do not need user-facing semantic versions.
- **XC-013** Model releases MUST have their own version and promotion record.

## 21. Dependency maintenance

- **REN-001** Renovate MUST manage dependency update pull requests.
- **REN-002** Renovate SHOULD use the maintainers' best-practices preset as the base, subject to project-specific review.
- **REN-003** Routine updates SHOULD be grouped into Python runtime, Swift packages, GitHub Actions, and development/tooling groups.
- **REN-004** Routine patch and minor updates SHOULD arrive on a weekly schedule in America/Chicago time.
- **REN-005** Security updates SHOULD be opened promptly and MUST NOT wait for the normal batch window when delay creates material risk.
- **REN-006** Major updates MUST use separate pull requests.
- **REN-007** Automerge MAY be enabled only for selected low-risk patch updates with green required CI. It MUST NOT be enabled globally by version class.
- **REN-008** Django, psycopg, RevenueCat, OpenAPI generators, database tooling, and deployment actions SHOULD use normal PR review even for small updates until their update behavior is well understood.
- **REN-009** A minimum release age MAY be used to avoid immediate adoption of newly published packages.
- **REN-010** Xcode and SDK updates remain explicit workflow/toolchain decisions. Renovate does not own them.

## 22. Feature flags

- **FLAG-001** The baseline MUST NOT create a general feature-flag table, targeting engine, or external flag service.
- **FLAG-002** Architecture MUST allow deploy and release to be separated when a real feature needs it.
- **FLAG-003** The first real flag SHOULD be implemented as one explicit server-side setting with a deletion condition.
- **FLAG-004** A reusable feature-flag abstraction is justified only after multiple active flags create repeated behavior.

Current status: design for flags. Do not instantiate a flag system yet.

## 23. Infrastructure definition and bootstrap

### 23.1 Thin declarative operations

- **INF-001** Recurring Cloud Run service and job configuration MUST live in checked-in YAML or equivalent repository configuration.
- **INF-002** Cloud Run YAML SHOULD be validated with `gcloud` dry-run in relevant CI.
- **INF-003** Django migrations, Dockerfiles, GitHub workflows, mise tasks, test plans, OpenAPI, and Renovate configuration MUST live in the repository.
- **INF-004** One-time provider resources MAY be created manually when a concise runbook records the exact state.
- **INF-005** The project MUST NOT adopt Terraform or OpenTofu initially.
- **INF-006** The project SHOULD adopt OpenTofu when resource count, IAM relationships, repeated environments, or configuration drift make it simpler than native configuration.
- **INF-007** The project MUST NOT create a mandatory ops verify ritual that interrogates every provider before every deploy.
- **INF-008** Django startup validation, CI checks, provider-native validation, migration execution, and the deploy smoke check MUST each validate the seam they own.
- **INF-009** An optional `mise run doctor` command MAY diagnose a broken developer environment. It MUST NOT become a deployment gate.

### 23.2 One-time bootstrap resources

| Provider | Create once |
| --- | --- |
| Google Cloud | Project, enabled APIs, Artifact Registry, production/preview/runtime/migration/scheduler service accounts, Secret Manager entries, Workload Identity pool/provider, Cloud Run resources, Scheduler jobs, budget alerts. |
| Neon | Production project, development project, roles, baseline dev branch, pooled/direct URLs, restore settings. |
| RevenueCat | Project, Test Store, iOS app, premium entitlement, products/offerings, webhook, sandbox access policy. |
| Apple | Development and production App IDs, App Store Connect record, subscriptions, sandbox testers, Xcode Cloud workflows. |
| GitHub | Repository ruleset, Renovate app/config, WIF variables, required checks, preview label. |

## 24. Observability and alerting

- **OBS-001** Cloud Run structured logs MUST include request ID, release SHA, environment, route, status, and decision ID when applicable.
- **OBS-002** Sensitive values, exact locations, credentials, and raw network identifiers MUST NOT appear in logs.
- **OBS-003** The project SHOULD use one error-monitoring service, with Sentry as the baseline choice, for backend exceptions and iOS crashes.
- **OBS-004** Initial alerts MUST be actionable: production deploy failure, sustained API 5xx, scheduled-job failure, RevenueCat webhook failure, and database or provider quota risk.
- **OBS-005** The project MUST NOT build a broad metrics dashboard before a real operational question needs it.
- **OBS-006** Monitoring MUST NOT ping the database often enough to prevent Neon scale-to-zero.
- **OBS-007** A user support report SHOULD include app version, venue, approximate time, and hidden cover decision ID.
- **OBS-008** A decision-inspection admin view SHOULD reconstruct model release, evidence, nowcast adjustments, context revision, and resolver version.

## 25. Recovery and incident handling

### 25.1 Recovery order

| Failure | First response | Escalation |
| --- | --- | --- |
| Bad web revision | Restore Cloud Run traffic to the previous known-good revision. | Create a corrective PR. |
| Bad cover model | Issue and promote a new release that reproduces the previous accepted behavior. | Analyze challenger and evaluation receipts. |
| Failed migration before deploy | Stop deployment. Production web remains on the old revision. | Fix migration in a new PR. |
| Application rollback after additive migration | Roll back the app revision. Leave the compatible schema in place. | Use a later contract migration. |
| Database damage | Stop writes if needed. Restore with Neon PITR or snapshot. | Reconcile missing external events. |
| RevenueCat webhook outage | Keep recorded events and retry/reconcile. | Use RevenueCat customer state as repair input. |
| Secret exposure | Rotate the provider secret, add a new Secret Manager version, deploy, revoke old value. | Review logs and affected access. |

- **REC-001** The previous Cloud Run revision MUST be the normal application rollback target.
- **REC-002** Database rollback MUST use restore capability only for actual data damage or incompatible destructive change. It MUST NOT be the routine response to an application bug.
- **REC-003** The production restore procedure MUST be tested before public launch and after major provider changes.
- **REC-004** The project MUST keep concise runbooks for deployment rollback, database restore, secret rotation, and RevenueCat reconciliation.
- **REC-005** A production incident MUST create a corrective issue or PR only when follow-up is useful. It does not require a formal incident-management system.

Implementation reinterpretation (August 12, 2026): the earlier shorthand
"promote the previous model release" names the desired behavioral rollback, not
permission to resurrect a retired database row. Release identities and their
promotion/retirement intervals are immutable history. IlliniCover therefore
issues a fresh candidate identity, evaluates it against the current incumbent
with a fresh receipt, and promotes that new identity. This intentionally
narrows the literal OPS wording to preserve the stronger provenance invariant;
it does not waive explicit evaluation or operator promotion.

## 26. Security and access

- **ACC-001** Permissions MUST be capability-based. Humans and agents MAY use the same capabilities.
- **ACC-002** Neither human nor agent contributors SHOULD bypass required CI or destructive-migration safeguards during routine work.
- **ACC-003** The GitHub deployment identity MUST be restricted to the IlliniCover repository and required branch/event claims.
- **ACC-004** Preview and production Cloud Run service accounts MUST be separate.
- **ACC-005** The migration job MUST receive the direct database secret. The web service SHOULD NOT receive it unless another operation proves it necessary.
- **ACC-006** Django Admin MUST require staff authentication and MFA before public launch.
- **ACC-007** Test data and preview data MUST contain no production precise location or billing data.
- **ACC-008** Repository automation MUST use pinned or trusted actions and SHOULD pin action digests through Renovate.

## 27. Cost control

- **COST-001** Cloud Run production and preview MUST start with minimum instances 0.
- **COST-002** Cloud Run maximum instances MUST be set explicitly.
- **COST-003** The GCP project SHOULD have low billing budget alerts, such as an early warning near $1 and a second warning near the expected monthly ceiling.
- **COST-004** The project MUST use one shared preview service, not one permanent service per pull request.
- **COST-005** Preview Neon branches MUST expire.
- **COST-006** Artifact Registry MUST delete old unreferenced images.
- **COST-007** Xcode Cloud workflows MUST use path filters and small test matrices so the included compute hours are spent on relevant Apple work.
- **COST-008** The project MUST NOT keep a permanent staging environment only because it is conventional.
- **COST-009** When usage shows that a paid tier improves reliability or reduces engineering distortion, the project SHOULD pay rather than preserve zero cost at the expense of the product.

## 28. Repository layout

```text
IlliniCover/
  mise.toml
  compose.yaml
  renovate.json
  .env.example

  .github/workflows/
    ci.yml
    preview.yml
    deploy.yml
    model-evaluation.yml

  server/
    Dockerfile
    manage.py
    pyproject.toml
    uv.lock
    config/
    ... Django apps ...

  ios/
    IlliniCover.xcodeproj/
    xcshareddata/xcschemes/
      IlliniCover Local.xcscheme
      IlliniCover Preview.xcscheme
      IlliniCover.xcscheme
    Config/
      Local.xcconfig
      Preview.xcconfig
      Release.xcconfig
    TestPlans/
      Fast.xctestplan
      UI.xctestplan
      Integration.xctestplan
    ci_scripts/
      ci_post_clone.sh
      ci_pre_xcodebuild.sh
      ci_post_xcodebuild.sh

  android/
    # Added when Android work begins.

  api/
    openapi.json
    fixtures/

  data/
    cover/
    deals/
    venues/

  ops/cloudrun/
    prod-service.yaml
    preview-service.yaml
    migrate-job.yaml
    refresh-job.yaml
    nightly-job.yaml

  docs/operations/
    bootstrap.md
    xcode-cloud.md
    revenuecat.md
    rollback.md
    restore-database.md
    rotate-secret.md
```

- **REP-001** The repository MUST keep provider and workflow configuration near the code that depends on it.
- **REP-002** The repository MUST NOT duplicate one lifecycle across a mise script, GitHub workflow, and undocumented dashboard procedure.
- **REP-003** Generated transient artifacts MUST be ignored. Canonical OpenAPI and API fixture artifacts MUST be checked in.

## 29. mise task contract

| Task | Contract |
| --- | --- |
| `mise run setup` | Install project tools/dependencies, start local PostgreSQL, migrate, and seed deterministic development data. |
| `mise run up` | Start or verify local PostgreSQL, then run local Django. |
| `mise run down` | Stop local support services without deleting data. |
| `mise run db:reset` | Delete only local DB state, recreate, migrate, and seed. |
| `mise run lint:server` | Run the reproducible server lint operation. |
| `mise run typecheck:server` | Run the reproducible Python type check. |
| `mise run test:server` | Run the normal fast server suite against local/test PostgreSQL. |
| `mise run check:migrations` | Detect missing migrations and validate migration shape. |
| `mise run api:export` | Generate `api/openapi.json` from Django Ninja. |
| `mise run fixtures:export` | Generate canonical API fixtures from backend scenarios. |
| `mise run ios:build` | Build the selected local iOS scheme with the project Xcode. |
| `mise run ios:test` | Run the fast iOS test plan. |
| `mise run ios:boot` | Boot the dedicated simulator by UDID. |
| `mise run ios:reset-app` | Reset `IlliniCover.dev` state without erasing the simulator. |
| `mise run ios:screenshot NAME` | Capture the dedicated simulator framebuffer to `.artifacts/ui`. |
| `mise run preview` | Trigger the manual preview workflow for the current branch. This is an escape hatch, not the production deploy path. |
| `mise run doctor` | Optional diagnosis of local tools and services. Never a production gate. |

- **TASK-001** Task names MUST be discoverable through `mise tasks`.
- **TASK-002** Tasks MUST fail with direct error messages and nonzero status.
- **TASK-003** A task MUST NOT silently access production unless its name and documentation explicitly identify a production operation. No routine production task is required in mise.

## 30. Bootstrap sequence

### 30.1 Repository and local

1. Create the monorepo and root mise configuration.
2. Create `compose.yaml` with local PostgreSQL only.
3. Create `.env.example` and local Django settings.
4. Create initial Django migrations and `seed_dev` command.
5. Create the iOS project, dev bundle identity, shared schemes, `xcconfig` files, and test plans.
6. Create canonical backend scenarios and fixture export.

### 30.2 Google Cloud and GitHub

7. Create the GCP project in the selected region and enable Cloud Run, Artifact Registry, Secret Manager, IAM Credentials, and Cloud Scheduler APIs.
8. Create Artifact Registry and cleanup policy.
9. Create deploy, production runtime, preview runtime, migration, job, and scheduler service accounts with minimum roles.
10. Create Workload Identity Federation restricted to the IlliniCover repository.
11. Create Secret Manager entries with preview/production separation.
12. Create Cloud Run services and jobs from checked-in configuration.
13. Create GitHub ruleset, required checks, preview label, and workflow variables.

### 30.3 Neon

14. Create `illinicover-prod` and `illinicover-dev` projects in the chosen nearby region.
15. Create application and migration roles as needed.
16. Store pooled and direct URLs in the correct Secret Manager contexts.
17. Configure dev baseline data and preview branch expiration behavior.
18. Confirm the point-in-time restore window and run a restore drill before public launch.

### 30.4 RevenueCat and Apple

19. Create the RevenueCat project and confirm the Test Store works with `IlliniCover.dev`.
20. Create the premium entitlement.
21. Create the production iOS app, App Store products, offering, and webhook.
22. Use account UUIDs as App User IDs and restrict sandbox entitlement access for beta testers.
23. Create development and production Apple App IDs.
24. Configure Xcode Cloud Verify and TestFlight workflows.
25. Run a no-charge TestFlight purchase and verify backend entitlement reconciliation.

## 31. Acceptance criteria

| Area | Acceptance result |
| --- | --- |
| Local bootstrap | A clean clone reaches a working local Django API and seeded PostgreSQL through documented mise commands without Neon or GCP credentials. |
| PR hygiene | `main` rejects direct routine pushes. A PR with relevant green checks can be merged by an authorized human or agent without a required reviewer. |
| Selective CI | A documentation-only PR does not start PostgreSQL or Xcode Cloud. A server PR runs PostgreSQL tests. An iOS PR runs Apple verification. |
| Preview | Adding `preview` creates an expiring Neon dev branch, migrates and seeds it, deploys the current commit to the shared preview service, and reports the URL. |
| Production deploy | A merge builds one image, runs migrations, deploys Cloud Run, performs readiness, and can restore the previous revision. |
| Migration safety | A safe additive migration is automatic. A destructive migration is detected and follows the documented exceptional path. |
| Secret isolation | Preview cannot read production database or RevenueCat server secrets. GitHub stores no long-lived GCP key and no production application secret. |
| Neon hygiene | Local and CI do not consume Neon. Preview branches expire. Deep health checks do not keep the database awake. |
| Fixtures | Canonical fixture regeneration is deterministic. SwiftUI previews and UI tests use those fixtures. The small full-stack suite reaches real Django/PostgreSQL. |
| Simulator | The dedicated simulator can be booted, reset, exercised, and screenshot through documented mise/Xcode tools without relying on leftover state. |
| Billing | Development uses Test Store. TestFlight purchases use Apple sandbox and do not charge. RevenueCat webhooks update the server idempotently. |
| iOS release | `main` remains releasable. TestFlight and App Store distribution are explicit Xcode Cloud actions. |
| Recovery | Application revision rollback, newly issued model recovery, database restore, secret rotation, and RevenueCat reconciliation have concise tested runbooks. |
| Cost | Cloud Run scales to zero, max instances are capped, previews are shared and optional, old images are cleaned, and quota usage is reviewed. |

## 32. Deferred adoption triggers

| Deferred system | Adopt when |
| --- | --- |
| Feature-flag platform | Several active flags require targeting, audit, cleanup, or percentage rollout. |
| Redis/Celery | The workload requires many immediate asynchronous tasks, task priorities, worker pools, or task-specific retry semantics. |
| OpenTofu/Terraform | The project has enough cloud resources, IAM relationships, or repeated environments that native YAML/runbooks cause drift or repeated manual work. |
| Permanent staging | Multiple parallel release lines or a dedicated QA workflow need a stable preproduction endpoint. |
| Per-PR preview fleet | Concurrent teams regularly need several previews at once. |
| Merge queue | Concurrent merges frequently invalidate each other after CI. |
| Always-warm Cloud Run | Cold-start latency materially harms the product and paid minimum instances are justified. |
| Paid Neon tier | Usage nears limits, restore retention is inadequate, or production reliability needs paid guarantees. |
| 1Password integration | Shared development secrets or agent-managed secrets require a vault-based permission boundary beyond local `.env` and Secret Manager. |
| Broader iOS matrix | Supported devices or OS versions produce real regressions that one representative simulator does not catch. |

## Appendix A. Current provider assumptions

This appendix records facts that can change. The date of record is August 12,
2026. The normative architecture does not depend on exact quota numbers.

| Provider fact | Current assumption | Source |
| --- | --- | --- |
| Cloud Run pricing | Cloud Run has an always-free allowance and request-based services can scale to zero when minimum instances are 0. Jobs are billed only while tasks run. | S1, S2, S3 |
| Cloud Run cap | Google documents service-level maximum instances as a cost and database-connection safeguard and suggests starting with 3. | S4 |
| Cloud Run configuration | Services and jobs can be deployed from checked-in YAML. Service YAML supports dry-run validation. | S5, S6 |
| Neon Free | 100 projects; 100 CU-hours per project each month; 0.5 GB storage per project; up to 2 CU; 6-hour restore history; 5 GB public transfer. Free compute scales to zero after 5 minutes. | S7, S8, S9 |
| Neon preview lifecycle | Branches can have an expiration time through API, CLI, Actions, or console. | S10 |
| RevenueCat development | Test Store uses a test API key and produces production-shaped customer and entitlement behavior without store charges. | S11, S12 |
| RevenueCat identity | A custom non-guessable App User ID supports cross-device and cross-platform entitlements. Email should not be used as the App User ID. | S13 |
| Apple purchase testing | Apple sandbox does not charge. In-app purchases in TestFlight use sandbox and do not carry into production. | S14, S15 |
| Xcode 27 agents | Xcode exposes MCP through `xcrun mcpbridge`. Xcode 27 agents can boot simulators, install/launch apps, synthesize touches, capture screenshots, and render preview variants. | S16, S17 |
| Xcode Cloud | Apple Developer Program membership includes 25 Xcode Cloud compute hours each month. Workflows support build/test/archive and TestFlight post-actions. | S18, S19 |
| GitHub rules | Rulesets can require a PR without requiring approval. Actions support manual dispatch, event filtering, and concurrency groups. | S20, S21 |
| GitHub to GCP | Google recommends Workload Identity Federation over exported long-lived service-account keys. | S22 |
| mise | mise supports monorepo task discovery, namespacing, and inherited tool/environment configuration. | S23 |
| Renovate | Renovate supports recommended presets, grouping, schedules, selective automerge, and noise-reduction rules. | S24, S25 |

## Appendix B. Source register

- **S1** Cloud Run overview and free-tier model: <https://cloud.google.com/run>
- **S2** What is Cloud Run: <https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run>
- **S3** Cloud Run pricing: <https://cloud.google.com/run/pricing>
- **S4** Set maximum instances for services: <https://docs.cloud.google.com/run/docs/configuring/max-instances>
- **S5** `gcloud run services replace`: <https://docs.cloud.google.com/sdk/gcloud/reference/run/services/replace>
- **S6** Deploy container images to Cloud Run services: <https://docs.cloud.google.com/run/docs/deploying>
- **S7** Neon pricing: <https://neon.com/pricing>
- **S8** Neon public network transfer: <https://neon.com/docs/introduction/network-transfer>
- **S9** Neon scale-to-zero facts: <https://neon.com/faqs/managed-postgres-services-pay-active-compute>
- **S10** Neon branch expiration: <https://neon.com/docs/changelog/2025-08-15>
- **S11** RevenueCat sandbox testing: <https://www.revenuecat.com/docs/test-and-launch/sandbox>
- **S12** RevenueCat Test Store: <https://www.revenuecat.com/blog/company/revenuecat-test-store>
- **S13** RevenueCat customer identity: <https://www.revenuecat.com/docs/customers/identifying-customers>
- **S14** Apple sandbox purchase testing: <https://developer.apple.com/help/app-store-connect/test-in-app-purchases/overview-of-testing-in-sandbox/>
- **S15** Apple In-App Purchase testing and TestFlight: <https://developer.apple.com/in-app-purchase/>
- **S16** Giving external agents access to Xcode: <https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode>
- **S17** Xcode 27 release notes: <https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes>
- **S18** Get started with Xcode Cloud: <https://developer.apple.com/xcode-cloud/get-started/>
- **S19** Xcode Cloud workflow reference: <https://developer.apple.com/documentation/xcode/xcode-cloud-workflow-reference>
- **S20** GitHub ruleset rules: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets>
- **S21** GitHub Actions workflow syntax: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax>
- **S22** Google GitHub Actions authentication: <https://github.com/google-github-actions/auth>
- **S23** mise monorepo tasks: <https://mise.jdx.dev/tasks/monorepo.html>
- **S24** Renovate upgrade best practices: <https://docs.renovatebot.com/upgrade-best-practices/>
- **S25** Renovate noise reduction: <https://docs.renovatebot.com/noise-reduction/>

## Final operational statement

IlliniCover v2 uses local-first development, path-sensitive CI, optional
deployed preview, and automatic backend production deployment from `main`.
GitHub Actions owns backend delivery. Xcode Cloud owns Apple delivery. Cloud
Run, Neon, RevenueCat, and Google Secret Manager remain replaceable provider
boundaries. The normal path stays short; the exceptional path exists only for
exceptional risk.
