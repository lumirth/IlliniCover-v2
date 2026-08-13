# iOS product acceptance map

This file records the native client owner for each required surface. It is not
a substitute for simulator acceptance.

| Surface | Implementation | Automated receipt |
|---|---|---|
| Guest onboarding, optional foreground location | `Account/OnboardingFlow.swift` | `testOnboardingAndEmailCode` |
| Passwordless login and signup code flows | `Account/SignInFlow.swift`, `API/AppAPI.swift` | backend allauth flow tests plus UI flow |
| Cover board and three-row card | `Cover/CoverBoardView.swift` | `testPrimaryTabsAndReportSheet` |
| Context menu and long-press reporting | `Cover/CoverBoardView.swift` | `testBarContextMenu` |
| Venue detail and recent evidence | `Cover/VenueDetailView.swift` | simulator acceptance |
| Cover/vibe reporting and offline queue | `Reporting/CoverReportView.swift`, `Database/` | domain/database tests and UI flow |
| Nightly deals including empty venues | `Deals/DealsView.swift` | primary-tabs UI flow |
| Add/confirm/deny/correct composer | `Deals/DealComposerView.swift` | domain tests and simulator acceptance |
| Time Machine gate and query | `TimeMachine/TimeMachineView.swift` | `testPremiumTimeMachineWithAuthenticatedFixture` |
| IlliniCover Blue purchase and restore | `Billing/` | provider sandbox/device acceptance still required |
| Handbook cache/list/detail | `Handbook/` | simulator acceptance |
| Account deletion and guest rotation | `Account/AccountView.swift` | backend identity tests plus simulator acceptance |
| Theme, sort, location, onboarding/reset | `Account/SettingsView.swift` | simulator light/dark and Dynamic Type acceptance |

## Runtime lanes

- Production compilation authority: Xcode 26.6, Swift 6.3, iOS 26.5 SDK.
- Local Xcode 27 beta is an additional compatibility lane only.
- UI tests pass `-uiTesting` to select an in-memory API actor and file-backed
  temporary GRDB database. Normal Debug and Release launches always construct
  `LiveAPIClient`.
- Release has no RevenueCat key default. Distribution must inject an Apple
  public SDK key; Test Store is Debug-only.

## Latest automated receipt

**Fixture UI plan.**

The arm64 `IlliniCover Local` UI plan exited successfully under Xcode 27.0
(`27A5237l`), with xcresult environment `UI · Built with macOS 27.0`, on
`IlliniCover iPhone 16e`, iOS 26.5 build `23F73`, UDID
`644F64CD-23BA-4D3C-915E-6B2069961477`. The finalized result bundle is
`.artifacts/ios/UI-20260813T044111Z-37588.xcresult`: 151 total tests, 150
passed, one intentionally Integration-only generated-client smoke skipped, and
zero failures or expected failures. The plan uses `-uiTesting` and reports
`IC_CODE_REVISION=local`; it does not replace the normal `LiveAPIClient`,
Git-SHA-correlated runtime gate.

The result records two `Invalid frame dimension (negative or non-finite).`
runtime warnings. Assertions passed, but final runtime acceptance remains open
until those warnings are resolved or explicitly dispositioned and a bounded
normal-runtime log is inspected.

**Generated-client local-full-stack smoke.**

The separate `Integration` plan also exited 0 with `TEST SUCCEEDED` and
finalized `.artifacts/ios/Integration-20260813T050146Z-58176.xcresult` with
result `Passed`: one selected test, one passed, zero failed, zero skipped, and
zero expected failures. It ran the `Local full stack` configuration on the
same arm64 iPhone 16e/iOS 26.5 simulator and selected only
`testLiveAcceptanceGeneratedClientSmoke`.

That test launched `LiveAPIClient` with `-liveAcceptance`, traversed the
generated client to loopback Django and real local PostgreSQL, settled the Bars
surface, found the real `bar-card-kams` venue selector, and reached the stable
Deals venue row. The Deals assertion intentionally permits a zero-deal venue row:
the authoritative recurrence model correctly emits an empty slate when all
available history is older than 90 days. This receipt proves the local
generated-client/full-stack seam; it is not a production-backend, Git-SHA,
bounded-log, or visual-parity receipt.

## Still external to simulator automation

- Sandbox or Test Store transaction receipt and webhook mirror.
- Physical-device location accuracy.
- TestFlight purchase and account-cross-device proof.
- VoiceOver human listening pass at all accessibility sizes.
