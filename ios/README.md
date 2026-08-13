# Native iOS client

IlliniCover v2 is a SwiftUI application targeting iOS 18 and later. The
project is reproducibly generated with XcodeGen. The checked-in API client is
generated from `../api/openapi.json`; the generator package stays pinned for
deterministic regeneration without linking its host-only tool into iOS.

```sh
cd ios
make api
xcodegen generate
make resolve
make build
```

`make api` builds the pinned Swift OpenAPI Generator command-line tool for the
host when needed. Its tiny `Tools/OpenAPIGeneratorBootstrap` package resolves
only the host generator and its dependencies into `../.local`, independently
of all iOS packages and binary artifacts, and
replaces `IlliniCover/API/Generated/{Types,Client}.swift`.
`make api-check` proves those sources match the current contract byte for byte.
Normal app builds compile the checked-in generated sources directly. The Xcode
build-tool plugin is intentionally excluded because target-level simulator
builds with Xcode 26.6 incorrectly compile the generator's host-only core for
iOS and trip its platform guard.

`project.yml` remains the generator authority, while the generated project and
shared schemes are also checked in so Xcode Cloud and a fresh clone can open
the project without a bootstrap race. `make generate-check` regenerates and
diffs this provider-facing artifact. Production code always uses
`LiveAPIClient`. The explicit Debug `-uiTesting` seam serves backend-exported
JSON from `api/fixtures` through the same generated client before mapping it to
domain models; Release ignores that launch argument.

Debug `-liveAcceptance` is a separate runtime-proof lane: it still uses
`LiveAPIClient` and refuses every non-loopback API origin. Its protected cache,
outbox, settings, and Keychain namespace persist across relaunch so offline
behavior can be proved. Launch once with
`-liveAcceptance -resetLiveAcceptance` before a new fixture profile; product
presentation stays blocked until that acceptance-only local state is cleared.
Release builds ignore the acceptance mode.

The one app target has three fail-closed configurations and shared schemes:

- `IlliniCover Local`: `com.illinicover.app.dev`, loopback HTTP, Test Store,
  visible LOCAL marker, and the only ATS local-network exception.
- `IlliniCover Preview`: the same side-by-side development bundle, the exact
  shared preview Cloud Run allowlist, Test Store, and a visible PREVIEW marker.
- `IlliniCover`: `com.illinicover.app`, exact production origin, no marker or
  ATS exception. Xcode Cloud must inject the Apple `appl_…` public SDK key and
  exact deployed 40-character lowercase Git commit SHA; missing/wrong values
  abort launch.

Configuration values are Info.plist build settings, not an ordinary Debug
redirect control:

- `IC_API_BASE_URL` — exact environment-owned Django origin.
- `IC_REVENUECAT_API_KEY` — RevenueCat public SDK key. Debug pins the public
  Test Store key and the existing four-package offering. Release deliberately
  has no default and requires the future Apple public SDK key; it never falls
  back to Test Store. RevenueCat is configured only after an IlliniCover
  account UUID is authenticated.
- `IC_SENTRY_DSN` — public Sentry DSN. Monitoring remains completely disabled
  when blank. The client sends crash/error correlation only: no PII, request
  bodies/headers/URLs, breadcrumbs, screenshots, session replay, or traces.
- `IC_SUPPORT_EMAIL` and `IC_PRIVACY_POLICY_URL` — enable the native Support
  mail handoff and published-policy link. Blank values display a clear beta
  release gate rather than a fake destination.
- `IC_CODE_REVISION` and `IC_ENVIRONMENT` — non-secret release correlation
  tags shared with backend/jobs monitoring. Production `IC_CODE_REVISION` is
  the exact Git commit deployed to Cloud Run, not a separate source-context
  digest.

The root `mise` tasks address one explicitly supplied simulator UDID for build,
test, boot, in-app development-state reset, and framebuffer screenshots. See
`docs/XCODE_CLOUD.md` for the checked-in repository half of Xcode Cloud.

Every repository-owned local `xcodebuild` command shares
`../.local/DerivedData`; package resolution, compilation, and tests reuse that
single cache instead of accumulating per-receipt trees. Logs and result
receipts keep distinct names outside the cache. A genuinely clean diagnostic
may opt into one isolated cache explicitly:

```sh
ILLINICOVER_XCODE_CACHE_MODE=diagnostic \
ILLINICOVER_XCODE_CACHE_SUFFIX=rfc3339 \
mise run ios:test
```

The diagnostic suffix is required and restricted to a safe filename. Routine
commands must not override the DerivedData path. Xcode Cloud's provider-managed
workspace cache is outside this local-only convention.
