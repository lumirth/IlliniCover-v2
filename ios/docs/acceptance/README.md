# iOS runtime acceptance

Acceptance exercises the normal app against a real Django/PostgreSQL backend.
SwiftUI previews, bundled JSON, fake API clients, source inspection, and a
successful build do not establish runtime behavior.

For each release candidate, retain one CI or release artifact named by the Git
commit and containing:

- the installed app identity, Xcode/iOS versions, device and simulator UDID;
- settled screenshots and accessibility trees in light and dark appearance;
- bounded app and server logs covering the captured interactions;
- the `.xcresult` for unit, integration, and UI tests; and
- a short manifest listing the completed scenarios and any unresolved failure.

The provider artifact is the evidence store. Do not copy screenshots, logs,
accessibility dumps, or result bundles into Git and do not maintain separate
fixture revisions or checksum ledgers.

## Required scenarios

| Surface | Behavior to establish |
| --- | --- |
| Board and venue | Fresh, historical, ranged, advertised, unavailable, cached/offline, sorting, detail, navigation and share |
| Cover report | Confirm, adjust, manual entry and boundaries, vibes/location, high-price confirmation, sent, queued and permanent failure |
| Deals | Empty and populated venues, supported price/timing/serving shapes, sorting, confirm/deny, offline queue and stale state |
| Deal editing | Search, canonical/custom selection, add/correct, validation, sent, queued and permanent failure |
| Identity and privacy | Guest issue/rotation, sign-in/link conflict, simple retry and orphan handling, deletion, unreadable-secret failure and erasure |
| Entitlement | Signed out, free, premium, provider outage and reconciliation without blocking core browsing |
| Accessibility | VoiceOver labels/actions, large Dynamic Type, focus/keyboard, reduced motion and contrast in representative long-content states |
| Release | Clean install, cold launch, relaunch with persisted cache/outbox, `/health/ready`, `/api/status`, and no unexpected bounded logs |

Transport failures may be injected at the real network boundary. Provider
states such as location permission and purchases must be exercised through the
system/provider surface; they may not be relabeled fixture results. A failed or
unrun row remains explicit in the artifact manifest instead of being papered
over with older evidence.
