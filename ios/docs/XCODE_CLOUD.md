# Xcode Cloud repository contract

IlliniCover keeps Xcode Cloud workflow policy in App Store Connect while this
repository owns every reproducible input: the checked-in Xcode project, shared
schemes, xcconfigs, test plans, and the three thin `ci_scripts` hooks.

Repository-owned local commands reuse the single `.local/DerivedData` cache
selected by `scripts/xcode-derived-data-path.sh`; isolated clean-room caches
require the explicit diagnostic mode and suffix documented in `ios/README.md`.
Xcode Cloud retains its provider-managed cache and does not create repo-local
DerivedData trees.

## Verify workflow

- Pin Xcode 26.6 (or the production-authoritative stable successor).
- Start for pull requests that touch `ios/**`, `api/openapi.json`, or
  `api/fixtures/**`. Do not start for documentation-only/backend-only changes.
- Use shared scheme `IlliniCover Local` and test plan `Fast` for every matching
  change. Add plan `UI` only for client/UI/fixture changes.
- Keep tests serial or low-parallelism and retain failed `.xcresult` bundles.
- Do not archive or distribute from this workflow.

## Integration workflow

This is manual or scheduled, not a PR blocker. Start local Django against the
normal disposable PostgreSQL seed, then use `IlliniCover Local` and
`Integration.xctestplan`. The plan has one guarded nonzero UI test that launches
`-liveAcceptance`, which is Debug- and loopback-only, and therefore cannot send
synthetic evidence to Preview or Production. The workflow must set
`ILLINICOVER_INTEGRATION=1` in the test-plan environment.

## TestFlight workflow

- Manual action or release tag only; merging `main` never distributes a build.
- Use shared scheme `IlliniCover`, configuration `Production`, and a clean
  archive.
- Inject `ILLINICOVER_REVENUECAT_APPLE_KEY` as a secret Apple public SDK key
  matching `appl_…` and `ILLINICOVER_CODE_REVISION` as the exact immutable
  40-character lowercase Git commit SHA deployed to Cloud Run. This is the
  shared release correlation authority; do not substitute a source-context
  hash that the deployment does not advertise.
- Inject `ILLINICOVER_SENTRY_DSN` and `ILLINICOVER_SUPPORT_EMAIL` when those
  external public integrations are provisioned. They expand through explicit
  Production build-setting seams; leaving either blank keeps that feature
  visibly disabled. A supplied value is validated by the target build phase.
- Add those names as Xcode Cloud environment variables. The Production
  xcconfig expands them into app build settings, and the app target's
  `Validate environment boundary` pre-build phase rejects the archive before
  compilation if either expansion is absent or malformed. This gate does not
  depend on an optional `CI_XCODE_SCHEME` variable.
- Production fails closed if either value, the production origin, or bundle
  identity is wrong. It has no cleartext ATS exception and no environment badge.
- Distribution signing stays Xcode Cloud-managed. Do not store `.p12` files,
  provisioning profiles, Sentry DSNs, or public-support release values in Git.

The shared Preview origin is reserved in source but is an external availability
gate until the provider service is provisioned and read back. Provider workflow
changes and final distribution remain explicit dashboard actions.
