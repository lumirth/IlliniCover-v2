# iOS product acceptance map

The client is always the native SwiftUI app backed by `LiveAPIClient`. Tests do
not substitute a fixture API or a second domain model.

| Surface | Implementation | Required proof |
|---|---|---|
| Guest onboarding and report-time optional location | `Account/OnboardingFlow.swift`, `Location/` | UI pass; physical-device location check |
| Passwordless sign-in and signup | `Account/SignInFlow.swift`, `API/AppAPI.swift` | backend auth tests; live UI flow |
| Cover board, venue detail, history, and reporting | `Cover/`, `Reporting/` | unit invariants; live UI flow |
| Offline report queue | `Database/` | cache/outbox lifecycle test; reconnect flow |
| Deals and add/confirm/deny/correct reporting | `Deals/` | unit invariants; live UI flow |
| Time Machine | `TimeMachine/` | authenticated entitlement flow |
| Blue purchase and restore | `Billing/` | provider sandbox/device receipt |
| Handbook | `Handbook/` | live UI flow |
| Account deletion and guest rotation | `Account/AccountView.swift` | backend identity tests; device privacy pass |
| Theme, sort, location, reset, and accessibility navigation | `Account/SettingsView.swift` | `testPrimaryNavigationIsAccessible`; human VoiceOver/Dynamic Type pass |

## Verification lanes

- `Fast`: compact model, provenance, configuration, Keychain, database, and
  privacy-manifest invariants.
- `UI`: `Fast` plus primary navigation/accessibility on the dedicated simulator.
- `Integration`: the real local server and PostgreSQL through `/api/`; no
  fallback or fixture transport.
- TestFlight/device: purchases, account handoff, physical location, VoiceOver,
  and bounded production logs.

Build and simulator success do not replace the live-backend or device rows.
Current evidence artifacts follow `docs/acceptance/README.md`.
