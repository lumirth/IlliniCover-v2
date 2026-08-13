# v1 to v2 iOS runtime comparison

Status: **draft receipt, awaiting the final normal-runtime candidate run**. The
captures below are durable evidence of the visual and interaction comparison
performed on August 12, 2026. A current arm64 fixture plan and a separate local
full-stack `LiveAPIClient`/generated-client smoke now have terminal passing
receipts, documented below. This file is still not proof of a committed
Git-correlated normal-runtime visual candidate, a production backend, or a
RevenueCat transaction.

## Comparison boundary

Both apps were installed and exercised on the same simulator:

- Device: `IlliniCover iPhone 16e`
- UDID: `644F64CD-23BA-4D3C-915E-6B2069961477`
- Runtime: iOS 26.5, runtime build `23F73`
- Screen captures: 1170 x 2532 pixels

The two data sources are intentionally different:

- **v1 is the live reference app.** The Release simulator app is
  `com.illinicover.app`, version 1.0.0 (1), built from v1 commit
  `fcb72222dfffcf2b2a58b84a1144d12d650f2eae`. It opened its actual local
  state. The backend was unavailable during this run, so its settled screens
  show the real “Account features are paused” banner while cached browsing
  continues.
- **v2 is deterministic UI evidence.** The Debug simulator app is
  `com.illinicover.app.v2`, launched with `-uiTesting -skipOnboarding
  -signedIn`. That explicit test-only argument selects `PreviewAPIClient` and
  controlled local data. Normal Debug and Release launches construct
  `LiveAPIClient`; the fixture seam is not a production fallback.

The fixture values therefore are not expected to equal v1's live cached
values. This receipt compares layout, hierarchy, native interaction, copy, and
the intended v2 product extensions. It does not claim pixel-for-pixel parity or
network end-to-end coverage.

A later exact-source v1 run repaired the simulator entitlement and produced 39
clean `v1-priority-*` screenshot/hierarchy/bounded-log triples without the
account-paused banner. Those artifacts are valid evidence for the v1 half of
their states, but they still are not matched to the newest normal
`LiveAPIClient` v2 binary. The older representative table below remains a
record of its original comparison run rather than being retroactively relabeled.

## Preserved product surface

The side-by-side run establishes the same core interaction model:

- Three native tabs—Bars, Deals, and Settings—with large titles, a compact
  floating tab bar, rounded venue/deal rows, and isolated Right/Wrong actions.
- Bars keep the venue, cover value, freshness/provenance, and report controls
  in a scan-friendly row. v2 deliberately represents more states: scalar
  prices, price ranges, unavailable cover, live/mixed/historical provenance,
  and explicit cached/offline status.
- A long press on a venue opens a native context menu with the same three
  actions and copy: “Open details,” “Report right price,” and “Report wrong
  price.” The v2 accessibility hierarchy independently records all three
  actions.
- Reporting opens a native, resizable sheet rather than an Expo-shaped custom
  overlay. Both versions retain Cancel/Submit, $5 decrement and increment,
  quick choices for $0/$5/$10/$20, and Clear/Don't Know. v2 adds the manual
  “Enter price” field, nearest-$5 disclosure, vantage selection, and an
  explicit submit gate.
- Deals remain grouped by venue with separate confirm and deny targets. v2
  adds ranged prices, serving/timing details, an explicit “Add Deal” action,
  stable suggestion search, and fuller add/correct forms. Empty venues remain
  visible rather than disappearing.

Representative pairs:

| Surface | v1 live reference | v2 deterministic fixture |
|---|---|---|
| Bars, dark | [`v1-bars-dark.png`](v1-bars-dark.png) | [`v2-bars-dark.png`](v2-bars-dark.png) |
| Venue context menu | [`v1-bars-context-menu.png`](v1-bars-context-menu.png) | [`v2-bars-context-menu-final.png`](v2-bars-context-menu-final.png) |
| Adjust-cover sheet | [`v1-adjust-sheet.png`](v1-adjust-sheet.png) | [`v2-adjust-sheet-final.png`](v2-adjust-sheet-final.png) |
| Deals, dark | [`v1-deals-dark.png`](v1-deals-dark.png) | [`v2-deals-dark.png`](v2-deals-dark.png) |
| Settings | [`v1-settings-dark.png`](v1-settings-dark.png) | [`v2-settings-light-final.png`](v2-settings-light-final.png) |

## Native interaction and accessibility receipts

The settled v2 screenshots are paired with captured accessibility hierarchies,
not inferred solely from pixels:

- Bars and report targets:
  [`v2-bars-light-final.png`](v2-bars-light-final.png),
  [`v2-bars-light-final.hierarchy.txt`](v2-bars-light-final.hierarchy.txt)
- Context menu:
  [`v2-bars-context-menu-final.png`](v2-bars-context-menu-final.png),
  [`v2-bars-context-menu-final.hierarchy.txt`](v2-bars-context-menu-final.hierarchy.txt)
- Adjust-cover sheet:
  [`v2-adjust-sheet-final.png`](v2-adjust-sheet-final.png),
  [`v2-adjust-sheet-final.hierarchy.txt`](v2-adjust-sheet-final.hierarchy.txt)
- Venue detail and recent reports:
  [`v2-bar-detail-final.png`](v2-bar-detail-final.png),
  [`v2-bar-detail-final.hierarchy.txt`](v2-bar-detail-final.hierarchy.txt)
- Time Machine:
  [`v2-time-machine-final.png`](v2-time-machine-final.png),
  [`v2-time-machine-final.hierarchy.txt`](v2-time-machine-final.hierarchy.txt)
- Settings and account-adjacent navigation:
  [`v2-settings-light-final.png`](v2-settings-light-final.png),
  [`v2-settings-light-final.hierarchy.txt`](v2-settings-light-final.hierarchy.txt)
- Offline Handbook:
  [`v2-handbook-final.png`](v2-handbook-final.png),
  [`v2-handbook-final.hierarchy.txt`](v2-handbook-final.hierarchy.txt)

The hierarchy captures confirm readable combined venue summaries, separately
addressable report actions, native Back/Cancel/Submit controls, the report
field hint “Enter price,” and navigable Settings rows for IlliniCover Blue,
Handbook, Privacy & Data, Support, sort, appearance, and location. Each accompanying
`.hierarchy.stderr` contains only Maestro's local `23-valhalla` version-parser
warning; the hierarchy command still returned the durable tree.

## Intentional v2 additions

These surfaces have no direct v1 parity target and are accepted as v2 product
work rather than visual drift:

- Venue detail with recent cover and vibe evidence, tonight's deals, decision
  correlation, and entry into Time Machine.
- Time Machine's date/time query and explicit retrospective-reconstruction
  disclosure.
- Deal composition with searchable suggestions and complete price, serving,
  timing, confirmation, denial, and correction state.
- Handbook cache/list/detail behavior, including a visible saved-copy state
  while offline.
- IlliniCover Blue, Privacy & Data, Support, expanded settings, passwordless
  account flows, account deletion/guest rotation, and visible offline-outbox
  state.

Additional durable screenshots are
[`v2-deal-composer.png`](v2-deal-composer.png),
[`v2-deal-search.png`](v2-deal-search.png),
[`v2-bar-detail-final.png`](v2-bar-detail-final.png),
[`v2-time-machine-final.png`](v2-time-machine-final.png), and
[`v2-handbook-final.png`](v2-handbook-final.png).

## Light and dark appearance

v2 was observed in distinct light and dark appearances on this simulator:
[`v2-bars-light-final.png`](v2-bars-light-final.png) and
[`v2-bars-dark.png`](v2-bars-dark.png). Text, semantic colors, cards, menus,
sheets, and tab selection remain legible in both.

The v1 control capture requested after switching the simulator to light
appearance, [`v1-bars-light.png`](v1-bars-light.png), remained visually dark in
that live run. That is an observed v1 runtime behavior, not a claim that every
v1 installation always ignores appearance changes. v2's verified light result
is therefore the relevant acceptance evidence for the new implementation.

## Toolchain and build receipts

The project has two deliberately separate lanes:

1. **Production compilation authority:** Xcode 26.6 (`17F113`), Swift 6.3,
   iOS 26.5 SDK. `.local/v2-stable-noassets-final.log` records `BUILD
   SUCCEEDED` at 09:48 using this toolchain. Assets were explicitly excluded to
   avoid the installed SDK/runtime build mismatch, so this proves Swift
   compilation and linking only; it is not an install/launch receipt and it
   predates later source changes.
2. **Compatibility and simulator runtime lane:** Xcode 27 beta. The older
   screenshot candidate used build `27A5194q`; the current terminal fixture
   test receipt below used Xcode 27.0 build `27A5237l` and arm64 on the same
   iOS 27 SDK, with the resulting full-assets app installed on the iOS 26.5
   simulator above. `.local/v2-xcode27-candidate.log` records `BUILD SUCCEEDED`
   for the 09:59 screenshot candidate. `.local/v2-resend-build.log` records a
   later full-assets `BUILD SUCCEEDED` after the email-code resend work, but no
   post-resend settled runtime capture is claimed here.

The earlier `.local/v2-build-for-testing-2.log` and
`.local/v2-unit-tests-precontract.log` remain historical incomplete receipts;
neither is counted as the current test result.

### Current arm64 fixture test receipt

`xcodebuild` exited 0 and finalized
`.artifacts/ios/UI-20260813T044111Z-37588.xcresult` with result `Passed`:

- scheme `IlliniCover Local`, test plan `UI`, configuration `Fixture UI`;
- Xcode 27.0 (`27A5237l`), arm64; xcresult environment `UI · Built with macOS
  27.0`;
- `IlliniCover iPhone 16e`, UDID
  `644F64CD-23BA-4D3C-915E-6B2069961477`, iOS 26.5 build `23F73`;
- 151 total tests: 150 passed, one skipped, zero failed, and zero expected
  failures;
- the skipped test was the intentionally Integration-only generated-client
  smoke, which requires the separate local Django/PostgreSQL test plan;
- the Swift unit portion independently reports 134 tests in 14 suites passed;
- the UI portion independently reports 17 executed, one skipped, and zero
  failures.

The result contains two SwiftUICore runtime warnings with the same message,
`Invalid frame dimension (negative or non-finite).`, surfaced during the
cleared-maximum-cover and manual-editor/high-price-alert tests. They did not
fail the assertions, but this receipt must not be described as warning-free.
After the tests passed, Xcode's simulator diagnostics collector waited 600
seconds and timed out; `xcodebuild` then finalized the xcresult and returned
success. That post-test delay is not a bounded app-log receipt.

This plan sets `IC_CODE_REVISION=local` and `-uiTesting`, so it proves the
current local fixture build, unit/privacy behavior, native interaction
assertions, and IlliniCover Blue hierarchy/copy. It does not establish a
40-character Git SHA, exercise `LiveAPIClient`, or close the matched visual and
production-runtime rows.

### Current local-full-stack integration receipt

`xcodebuild` exited 0 with `TEST SUCCEEDED` and finalized
`.artifacts/ios/Integration-20260813T050146Z-58176.xcresult` with result
`Passed`:

- scheme `IlliniCover Local`, test plan `Integration`, configuration `Local
  full stack`;
- arm64 on `IlliniCover iPhone 16e`, UDID
  `644F64CD-23BA-4D3C-915E-6B2069961477`, iOS 26.5 build `23F73`;
- one selected test, one passed, zero failed, zero skipped, and zero expected
  failures;
- only `testLiveAcceptanceGeneratedClientSmoke` was selected;
- `LiveAPIClient` traversed the generated transport through loopback Django to
  real local PostgreSQL, settled Bars, exposed real venue selector
  `bar-card-kams`, and reached the stable Deals venue row.

The result summary records no runtime warnings. The Deals assertion correctly
targets the stable venue row rather than requiring a populated deal: the
authoritative recurrence model emits an empty slate when every available
history row is older than 90 days. This terminal receipt proves the local
generated-client/full-stack seam. It does not prove production reachability,
bind the build to a Git SHA, supply a bounded app log, or replace the matched
visual comparison.

The 09:59 v2 launch helper receipt identifies PID 53299 and bundle
`com.illinicover.app.v2`. Its attached unified-log capture contains no app
crash, but it remained attached long enough to include later processes and is
not a bounded final-candidate log. A new bounded log receipt is required below.

## v1 Xcode 27 / iOS 27 limitation

Two v1 launch attempts in the Xcode 27/iOS 27 compatibility experiment
terminated with `EXC_BREAKPOINT` / `SIGTRAP` in
`___UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption_block_invoke`:

- `~/Library/Logs/DiagnosticReports/Retired/IlliniCover-2026-08-12-085446.ips`
- `~/Library/Logs/DiagnosticReports/Retired/IlliniCover-2026-08-12-085452.ips`

Both receipts identify v1 bundle `com.illinicover.app`, version 1.0.0 (1). This
is a v1 scene-lifecycle compatibility failure, not evidence about v2. It is also
why the behavioral comparison uses the same settled iOS 26.5 runtime for both
apps. [`v1-launch-ios26.5.png`](v1-launch-ios26.5.png) was captured before v1
settled and is retained only as an investigation artifact; it is not used as
acceptance evidence.

## Unresolved gates

The existing artifacts do **not** close these gates:

- Repeat the Xcode 26.6 compile receipt against that final source revision.
- Commit the accepted tree and bind the iOS and backend release receipts to the
  same exact Git SHA; both terminal receipts are local receipts rather than
  source-bound release receipts.
- Use the newest Git-correlated normal `LiveAPIClient` binary on the exact
  iPhone 16e/iOS 26.5 simulator to capture settled UI/accessibility at the
  still-open matched visual states. The local full-stack smoke proves only the
  Bars/Deals transport and reachability seam.
- Resolve or explicitly disposition the two invalid-frame runtime warnings in
  the final candidate.
- Capture and inspect a bounded final-candidate log. Absence of a crash in an
  earlier or open-ended log is not equivalent to this gate.
- Complete external/provider acceptance separately: RevenueCat transaction and
  restore, webhook mirror, physical-device location accuracy, TestFlight and
  cross-device ownership, and a human VoiceOver pass.

## Final candidate receipt — **pending update**

Replace this section after the newest binary is built and exercised. Record:

- source/OpenAPI revision and exact successful build/test log names;
- installed `.app` path, bundle identifier, launch arguments, PID, device UDID,
  runtime build, and settled timestamp;
- final screenshot and accessibility-hierarchy links for Bars, context menu,
  report sheet, account-code resend, Privacy & Data, and Support;
- bounded log filename/window plus the first warning or failure, or an explicit
  statement that no app-scoped warning/error/crash appeared in that window.

Until that update is present, the older screenshots remain useful comparison
evidence but must not be described as the final v2 runtime acceptance receipt.
