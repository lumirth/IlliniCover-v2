# Visual state acceptance matrix

This is the runtime gate for IlliniCover's primary surfaces. A compiler pass,
SwiftUI preview, or `PreviewAPIClient` screenshot does not satisfy a row.

## Evidence rules

- `PAIR`: capture v1 and the newest v2 binary on the same iPhone 16e / iOS
  26.5 simulator, at the same navigation depth and interaction state. Dismiss
  unrelated alerts first.
- `V2`: the state is new to v2 or cannot honestly be produced by v1; capture
  the newest v2 binary only.
- `L`: serve deterministic state from the local Django acceptance database
  through `LiveAPIClient` and the generated OpenAPI client.
- `I`: derive the state by interacting with an `L` fixture.
- `T`: inject a bounded transport/cache failure while retaining the real
  client, database, and outbox paths.
- `S`: exercise a system or provider state. Never relabel a fixture as
  provider proof.

Every accepted capture records the app build/revision, fixture revision,
device/runtime/UDID, appearance, screenshot, settled accessibility hierarchy,
and bounded app/server logs. Representative content states are captured in
light and dark appearance. Long-content states also receive a large Dynamic
Type pass. A screenshot with a banner or alert unrelated to the tested state
is rejected.

## Bars / cover board

| ID | Kind | Required state and interaction | Runtime evidence |
| --- | --- | --- | --- |
| B1 | L / PAIR | Fresh live single, historical single, mixed/range, unusual or unconfirmed, and unavailable cards; include long venue/price overflow and a raw off-step historical decision. | Open |
| B2 | L / V2 | Advertised single, advertised-conflict range, and unavailable language. | Open |
| B3 | I / PAIR | Whole-card body opens venue detail and its long press opens the card menu; Right tap opens Confirm; Right long press exposes and executes Quick Confirm; Wrong tap opens Adjust; Wrong long press exposes $0/$5/$10/$20; an amount equal to the displayed price opens Adjust. Capture menus before actions and destinations/receipts after. The v2-only Other Price extension, if retained, is captured separately rather than called v1 parity. | Open |
| B4 | T / V2 | Cached-first then refreshed, cached offline, freshness aging past one hour, and empty-cache failure with Retry. | Open |
| B5 | I / PAIR | Open Date (Old-New), Name (A-Z), Lowest by Reports, and Recently Updated menus and resulting orders, with missing values last. | Open |

## Venue detail

| ID | Kind | Required state and interaction | Runtime evidence |
| --- | --- | --- | --- |
| D1 | L / PAIR | Same venue/state as its board card: metadata, Navigate and Share toolbar affordances, the intentional COVER card composition (status help, centered price, evidence, and estimate drill-in), Contribute, and recent reports. Capture status explanation closed/open/dismissed and the walking-directions handoff. The exported share image is intentionally different in v2 and is tested in D8. | Open |
| D2 | L / V2 | Live, historical, mixed/range, unusual, unavailable, and advertised cover states; vibes absent and populated. | Open |
| D3 | L / PAIR | The grouped recent-report preview and More Reports transition: empty; cover report with age/source/location/vibes; admitted vibe-only row; and more than four reports followed by the full history list. | Open |
| D4 | L / V2 | No deals and Tonight's Deals with current/likely/advertised rows, all supported price shapes, and serving/timing present and absent. | Open |
| D5 | I / PAIR | Contribute opens the direct report sheet for the same venue. | Open |
| D6 | T / V2 | Blocking cold-load failure and retry recovery. Venue detail currently has no cache; a cached-offline detail state is not claimed. | Open |
| D7 | S / V2 | Time Machine signed-out, signed-in non-premium, premium initial/loading, past reconstruction, future prediction, and API error. | Open |
| D8 | I / V2 | Export the approved branded venue share card and inspect the actual bitmap, not merely the source view: venue/cover context, IlliniCover identity, legibility in light/dark appearance, useful activity payload, no report-action controls, and app-link fallback when image sharing is unavailable. | Open |

## Deals list and drink rows

| ID | Kind | Required state and interaction | Runtime evidence |
| --- | --- | --- | --- |
| E1 | L / PAIR | Venue with real drink rows and venue with no deals; header name/count/add affordance; long name plus serving overflow; distinct timing/serving/price variants. | Open |
| E2 | L / V2 | Single/range/percent/unknown price; current/likely/advertised/unknown status; serving present/absent; all-night, until-sold-out, before, after, between, and unknown timing. Unknown timing stays omitted on the compact row. | Open |
| E3 | I / PAIR | Body tap opens Review; Confirm and Deny alerts each captured before Cancel and before Submit; sent receipt and every shared route. The v2 supplementary row context menu is captured and classified separately as a v2 extension, not claimed as v1 parity. | Open |
| E4 | T / V2 | Confirm/Deny queued offline versus permanent failure; cached offline; stale prior-service-night read-only state; no-cache failure and recovery. | Open |
| E5 | I / PAIR | Open Date, Name, Lowest by Reports, and Recently Updated menus and resulting orders, with empty venues last. | Open |
| E6 | I / PAIR | Header add button opens the Add composer. | Open |

## Cover submission

| ID | Kind | Required state and interaction | Runtime evidence |
| --- | --- | --- | --- |
| C1 | L + I / PAIR | Initial Confirm, Adjust, and direct Contribute sheets with the mode icon/title and venue subtitle; no redundant Cover Price section heading. Prefilled untouched submission remains valid evidence; unavailable decision has no prefill. | Open |
| C2 | I / PAIR | Card/menu/Right/Wrong entry depth, middle detent, expand/collapse, Cancel, and swipe dismissal. | Open |
| C3 | I / PAIR | Stepper tap and sustained accelerating hold, $0/$70 boundaries, Clear before $0/$5/$10/$20, then restore/edit. Haptics remain rate-limited during hold. | Open |
| C4 | I / PAIR | Isolated editor initial, partial decimal, invalid input, Cancel restore, nearest-$5 Done boundaries, empty and `.` clear, huge/non-finite paste, and disabled Submit while editing. | Open |
| C5 | I / PAIR | Above-$40 confirmation with exact title/message/actions, both cancel and report. | Open |
| C6 | L + I / V2 | Cover-only, vibe-only after Clear, combined; unknown/outside/inside vantage and corresponding vibe controls; selection/clear; location off/on. | Open |
| C7 | S / V2 | First location permission allowed/denied and location failure without permission. | Open |
| C8 | L + T / PAIR | Sent and queued-offline receipts plus auto-dismiss; permanent failure retained with retry; dismissal disabled while submitting. | Open |
| C9 | L + I / PAIR | Quick Confirm and every quick-Wrong sent/queued notice, with payload provenance matching the displayed decision. | Open |

## Deal composer and search

| ID | Kind | Required state and interaction | Runtime evidence |
| --- | --- | --- | --- |
| G1 | L + I / PAIR | Add auto-opens focused search; Review opens a prefilled form with collapsed price/quicks; Deny if retained as a reachable flow. | Open |
| G2 | L / PAIR | Search empty/recent and 0/1/6 results; canonical, display-name, and alias-only matches; long result; first-row cue; term/alias context; venue/global scope and relative date; keyboard Done chooses first or trimmed custom; cancel restores the prior name. Applying a suggestion preserves the full variant and separately flashes changed info and price surfaces. | Open |
| G3 | I / PAIR | Open Serving hierarchy in order: Each; Drinks (Can/Bottle/Pitcher/Shot/Pint/Glass); Food (Order/Basket/Plate); Other/custom. Open Timing hierarchy in order: All night/Until sold out/Unknown; Time-specific (Before/After/Between), followed by the native wheel popover for every required picker. Capture both the open controls and the form after selection. | Open |
| G4 | I / PAIR | Collapsed $1-$5 quick prices; expanded Single/Range/% off; steppers and partial text editing; Cancel/Done; range validation; $0/$100 bounds; no accidental internal separator. | Open |
| G5 | L + T / PAIR | Add and Review sent receipts with auto-dismiss, queued-offline receipt, permanent failure retained, and corrected result visible on Deals. | Open |

## Current evidence state

The exact-source v1 Release rebuild now launches cleanly on the comparison
simulator without the unrelated account banner. Its bounded run produced 39
accepted unobscured screenshot/hierarchy/log triples, including the open Deal
Composer menus and actual cover submission/quick-action receipts. Those
artifacts establish only the v1 side of a `PAIR` row. Known v1 runtime gaps are
Deal submission receipts, outer-sheet dismissal/detent transitions, an empty
Deal section, and post-sort resulting orders. Existing v2 priority captures
made with `PreviewAPIClient` remain rejected; each row stays open until the
newest normal `LiveAPIClient` v2 binary is captured at the matching state. The
fail-closed local Django fixture lane is available for the `L` and bounded `T`
rows.

A separate current arm64 `Fixture UI` test-plan receipt passed 150 of 151 tests
with the sole Integration-only smoke skipped and zero failures. It records two
`Invalid frame dimension (negative or non-finite).` runtime warnings. Because
that plan uses `-uiTesting`/`PreviewAPIClient`, carries code revision `local`,
and does not produce the state-matched screenshot/hierarchy/log bundles below,
it closes automated assertions but does not close an `L`, `T`, or `PAIR` row.
