# Xcode Cloud repository contract

The checked-in `IlliniCover.xcodeproj` is the sole project authority. Xcode
Cloud uses its shared schemes, xcconfigs, and test plans directly; there is no
project generator, OpenAPI generator, fixture backend, or repository CI hook.

## Pull requests

- Use the latest production-supported stable Xcode.
- Run scheme `IlliniCover Local` with test plan `Fast` for iOS changes.
- Also run plan `UI` when navigation or visible behavior changes.
- Retain failed xcresult bundles. Do not archive or distribute from this lane.

## Integration

Integration is a manual or scheduled real-stack lane. Start local Django and
PostgreSQL, then run `IlliniCover Local` with `Integration.xctestplan`. Its one
selected UI test reads the real unversioned `/api/` service. No synthetic
client backend exists.

## TestFlight

- Use shared scheme `IlliniCover`, configuration `Production`, and a clean
  archive from a manual action or release tag.
- Inject `ILLINICOVER_REVENUECAT_APPLE_KEY` as an `appl_…` public SDK key.
- Optionally inject `ILLINICOVER_SENTRY_DSN` and
  `ILLINICOVER_SUPPORT_EMAIL`; blank values disable those integrations.
- The target build phase rejects an invalid production origin, bundle identity,
  RevenueCat key, Sentry DSN, or support address.
- Keep signing Xcode Cloud-managed. Never store credentials, signing material,
  or private provider values in Git.
