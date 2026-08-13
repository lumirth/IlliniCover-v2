# Shared preview

Preview is optional and serial: add the `preview` label to a pull request, or
run `.github/workflows/preview.yml` manually with a branch/tag/commit. The fixed
`shared-preview` concurrency group prevents two provider mutations from
overwriting the single service.

The workflow checks out the requested ref and records that exact commit SHA. It
reads only the Neon dev-project API key through preview-scoped GCP WIF, creates
or resets an isolated `preview-pr-<number>` branch, and enforces a provider
expiration approximately 24 hours ahead (the timestamp is computed when the
serialized workflow starts). It stores the new direct/pooled URLs in
preview-only Secret Manager entries, migrates via the direct role, runs the
production-safe deterministic bootstrap via the pooled preview role, and then
deploys `illinicover-preview` with min 0/max 1. No production data is cloned.

Removing the label or closing the pull request deletes that branch. The Neon
expiration is the cleanup failsafe if GitHub cleanup cannot run. The two
preview database secrets keep only the current enabled version so temporary
branches do not accumulate active Secret Manager versions.

Before changing Neon or creating a secret version, the workflow inventories
Secret Manager metadata without reading payloads. It rejects disabled billable
versions, more than one incumbent per secret, a settled inventory above six,
or a two-version preview rotation above the bounded transition ceiling of
eight. It creates two candidate versions, pins their numeric versions in the
migration/bootstrap/service resources, and reads each reference back. Only
after migration, bootstrap, service readiness, and exact secret-reference
readback does it disable, verify, and destroy superseded preview versions. A
failed run retains the old accepted versions and stops later rotations until
an operator compares Cloud Run references and explicitly reconciles the
candidates; it cannot accumulate versions run after run.

Before enabling this workflow, confirm the variables listed in `bootstrap.md`,
create `illinicover-preview-web` and `illinicover-preview-migrate` JSON bundles
with distinct database capability and an initial preview-only Django key, and
prove that preview identities cannot access any production secret. The URL and Neon
branch name may be posted to the pull request; connection strings and API keys
must never be logged or attached.

If an older shared preview still references `latest`, take it out of service or
redeploy it once with its current numeric versions before enabling this
workflow. Numeric pinning is the authority after that one-time cutover.
