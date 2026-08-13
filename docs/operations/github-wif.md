# GitHub ruleset and Workload Identity Federation

Protect `main` with a pull request and the stable `CI / Required` check. Do not
require a reviewer by default. Keep any emergency bypass actor visible in the
GitHub audit log. Documentation-only pull requests should run classification
and the stable summary without starting PostgreSQL.

The production WIF provider must restrict the OIDC assertion to the exact
repository and `refs/heads/main`; the deployment service account must accept
only that provider principal set. Preview uses a distinct service account and
an equally narrow repository/workflow condition. Neither identity has a JSON
key. Validate the live provider attribute mapping and IAM policy readback before
enabling automatic deployment.

Grant workflows only repository read permissions plus the declared narrow
permissions. CI and deploy need read-only `actions` and `pull-requests` access
to bind an exceptional destructive migration to its exact PR and successful
preview receipt; deployment alone receives `id-token: write`. The provider
claim must still restrict production WIF to `main` even though GitHub metadata
is readable on pull requests.

The live providers are deliberately separate:

- production: `projects/1068900473446/locations/global/workloadIdentityPools/github-illinicover-prod/providers/github`;
- preview: `projects/1068900473446/locations/global/workloadIdentityPools/github-illinicover-preview/providers/github`.

Production reads repository variable `GCP_WORKLOAD_IDENTITY_PROVIDER`; preview
reads `GCP_PREVIEW_WORKLOAD_IDENTITY_PROVIDER`. Never point both workflows at
one provider merely because each later selects a different service account.
The `2026-08-13` metadata readback found both providers `ACTIVE`: production
requires repository `lumirth/IlliniCover-v2`, `refs/heads/main`, and exact
`deploy.yml@refs/heads/main`; preview requires the same repository, exact
`preview.yml@refs/heads/main`, and only `pull_request` or `workflow_dispatch`.
Both map repository, ref, workflow ref, event name, and subject claims. Service
account IAM readback remains a separate required receipt.

Repository variables hold resource identifiers only. GitHub must not store
production application secrets. A workflow may use its short-lived WIF token
to access its minimum infrastructure credential: preview reads only the Neon
dev-project API key. Production runtime secrets are mounted directly into
their least-privilege Cloud Run identities.

Provider setup is external to this repository. If any variable is empty or a
placeholder, the workflow fails before a build. Do not add a second local
routine production deploy task; `.github/workflows/deploy.yml` is the canonical
post-merge path.

The deploy identities inventory Secret Manager names, states, and version
numbers but never fetch production payloads. Give production metadata viewer
and version-manager capability only for `illinicover-web`,
`illinicover-migrate`, and `illinicover-jobs`; give preview the equivalent only
for `illinicover-preview-web` and `illinicover-preview-migrate`. Payload access
remains on the owning Cloud Run runtime identities. The version-manager grant
exists solely to disable/read-back/destroy an obsolete predecessor after all
accepted resources pin and verify its replacement. Audit the exact resource
bindings before enabling either workflow.
