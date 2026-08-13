# Implementation traceability

This is the live acceptance ledger for the v2 rebuild. A checked box requires
code plus proportionate verification; source existence alone is not evidence.
The latest real-PostgreSQL server receipt at this boundary is 302 passed with
three expected skips for the SQLite-only visual-acceptance seeder. The separate
data gate is seven passed. The checked-in OpenAPI SHA-256 is
`c83255d0e102a54d7ee7375bb264a6aa72ad67b34b85c343a38773d0ec033e0b`.

No checked row below asserts final cross-system release identity. The final
candidate receipt must bind one exact 40-character committed Git SHA to the
GitHub deployment, backend status/readback, and iOS distribution build. A local
`src-` upload-set digest is useful for manual or visual-acceptance correlation,
but it is not a substitute for that Git SHA.

## Foundation

- [x] Native SwiftUI iOS shell with native navigation and feature-focused code
- [x] GRDB cache, Keychain credentials, and restart-safe submission outbox
- [x] One Django/Ninja/allauth backend and PostgreSQL schema
- [x] Checked-in OpenAPI plus deterministically generated Swift client
- [x] Blank database migration and versioned import proof
- [ ] Final container/service/scheduler/health/log/Admin runtime receipt

Evidence: `scripts/ci/all.sh`, `ios/Makefile`, generated-client contract tests,
the versioned manifests under `data/`, and the final Cloud Run cutover receipt
still to be written. The earlier scale-to-zero web revision and three jobs
passed a live rollout/readback, but they predate the current repository policy,
the repository-defined refresh job is not live, and Scheduler is paused. The
newest committed source and policy revision must pass the complete cutover and
readback before the last row is checked.

## Cover and vibes

- [x] Installation actors and immutable submission envelope
- [x] Cover-only, vibe-only, and combined atomic submissions
- [x] Neutral missing account/location/history signals
- [x] One-report live behavior and singleton model-echo protection
- [x] Actor deduplication, conflict/range behavior, and trust admission classes
- [x] Historical model release, chronological receipt, and reproducibility
- [x] Venue and bounded campus nowcasts with decay
- [x] Decision receipts and retrospective/as-of Time Machine

Evidence: `server/submissions/tests`, `server/covers/modeling/tests`,
`server/covers/tests`, `docs/model/cover-historical-v1-selection.md`, and
`docs/operations/2026-08-12-database-drills.md`. Public reads reuse a unique
served-state receipt rather than writing on every request.

## Deals and content

- [x] Versioned deal import and model-selection analysis receipt
- [x] Nightly slate retaining empty venues and distinct deal variants
- [x] Add, confirm, deny, and correct evidence with lineage
- [x] Published handbook list/detail and local cache

Evidence: `tests/data`, `server/deals/tests`, `server/handbook/tests`, and
`docs/model/deal-recurrence-v1-selection.md`.

## Identity and IlliniCover Blue

- [x] Guest browsing/reporting and actor rotation/deletion
- [x] Passwordless verified-email account and multi-device actor linking
- [x] Account deletion/deidentification and session handling
- [ ] Complete RevenueCat purchase/restore/provider lifecycle receipt

The unchecked provider row is deliberately narrower than implementation. The
public product name is **IlliniCover Blue**; `premium` remains the stable
internal entitlement identifier. The settled U.S. slate is Annual $12.99 and
Monthly $1.99 as the primary choices, with Weekly $0.99, Six months $7.99, and
Lifetime $24.99 under the expanded choices. Annual, monthly, weekly, and
six-month access renew through Apple; lifetime is a one-time purchase.

The account-UUID identity, `premium` mirror, authenticated/idempotent HMAC
webhook, protected Time Machine, reconciliation, ordered events, and durable
async provider deletion are implemented and tested. RevenueCat test-webhook
delivery has also returned HTTP 200 and produced the expected durable event
receipt. The products and offering are mapped in RevenueCat, but an Apple/Test
Store purchase, restore, cross-device ownership, provider deletion, and
complete App Store product metadata still require live end-to-end receipts.

## iOS product acceptance

- [x] Cover board, venue detail, report sheet, recent reports, and Time Machine
- [x] Deals and deal report/correction flows
- [x] Handbook, onboarding, account, settings, IlliniCover Blue, and support surfaces
- [x] Current arm64 fixture unit/UI plan has a terminal passing receipt
- [x] Current arm64 generated-client/local-full-stack smoke has a terminal
      passing receipt
- [ ] Clean same-device v1/v2 runtime parity for priority flows: Deals list and
      drink-deal rows; deal composer/search/submission; quick confirm, deny, and
      body-edit; and cover reporting initial/menu/submenu/partial/validation/
      clear/edit/dismiss/receipt states. Every pair requires a screenshot plus
      hierarchy at the same navigation depth and interaction state on iPhone
      16e/iOS 26.5, with unrelated alerts dismissed and the newest
      LiveAPIClient v2 binary.
- [ ] Newest-binary simulator receipt with screenshots, hierarchy, and bounded logs

Evidence: `ios/docs/PRODUCT_ACCEPTANCE.md` and
`ios/docs/acceptance/RUNTIME_COMPARISON.md`. The current Xcode 27.0 arm64
fixture receipt is 151 total: 150 passed, one intentionally Integration-only
skip, and zero failures on the exact iPhone 16e/iOS 26.5 simulator. It carries
two `Invalid frame dimension (negative or non-finite).` runtime warnings and
identifies its code revision as `local`, so it is test authority but not final
Git-correlated normal-runtime acceptance. The separate Xcode 27.0 arm64
`Integration` receipt is one passed test with no failures or skips on the same
simulator. It proves `LiveAPIClient` reaches loopback Django and real local
PostgreSQL through the generated client, settles the Bars surface at KAMS, and
reaches the stable Deals venue row. That local seam proof is not production,
Git-SHA, bounded-log, or visual-parity acceptance. The older `v1-final-*` and
`v1-blocked-clean-reset-auth-banner.*` files retain the unrelated "Account
features are paused" blocker and are not parity evidence. The later 39
`v1-priority-*` screenshot/hierarchy/log triples are clean v1-side receipts,
but the matched v2 comparison captures are stale `PreviewAPIClient` fixtures.
Later diagnostics and the terminal integration smoke prove some
`LiveAPIClient` behavior and the generated-client wire seam, but do not form a
final-source matched parity set. Both open rows stay open until the remaining
v1 gaps and clean matched pairs use the newest generated-client/privacy/
Keychain v2 build at the same interaction states.

## Operations acceptance

- [x] Neon roles, TLS, hostname verification, channel binding, backups/PITR,
      and restore drill
- [x] Idempotent scheduled commands and advisory-lock concurrency proof
- [x] Context and email failures degrade without blocking guest cover use
- [ ] Newly issued model-recovery rollback drill (registration path implemented)
- [ ] Final external beta infrastructure and provider receipt

Evidence: `docs/operations/2026-08-12-neon-role-tls-receipt.md`,
`docs/operations/2026-08-12-database-drills.md`, the direct PostgreSQL identity
probe, and scheduled-command tests. The historical database drill re-promoted a
retired release before the append-only authority guard existed; it is not
current rollback proof. `issue_cover_model_recovery` now registers a fresh
candidate identity from a retired historical artifact without reviving prior
authority. Close the model-recovery row only after that candidate earns a new
receipt against the current incumbent, is promoted in an isolated drill, and
preserves both prior authority intervals.
The final row remains open. Artifact Registry still retains unreferenced image
layers pending provider garbage collection, but the owner accepts the modest
temporary storage charge and the release guard now enforces a bounded 1 GB
budget with 256 MiB build headroom. Completion still requires a
Git-SHA-correlated Cloud Run
rollout/readback, real SMTP, RevenueCat end-to-end delivery, monitoring
ingestion, distribution signing/TestFlight, complete App Store product
metadata, physical-device location, and a human VoiceOver pass.
