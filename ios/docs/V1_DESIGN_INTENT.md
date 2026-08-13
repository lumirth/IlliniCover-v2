# v1 design-intent ledger

This ledger is the behavioral and visual reference for rebuilding IlliniCover
v2 without copying v1 implementation. It exists because an unusual layout or
interaction is not evidence that the design was accidental.

## Authority and review rule

Apply evidence in this order:

1. the user's current explicit direction;
2. the accepted v2 product specification;
3. v1's dated mobile decisions and scoped mobile guide;
4. v1 source, tests, runtime evidence, and Git history.

Treat an established v1 behavior as intentional until the evidence identifies
it as an implementation fault. A native v2 implementation may replace an Expo
workaround, but it must preserve the intended visible composition and
interaction unless a deliberate v2 decision says otherwise. Ambiguity is a
product question, not permission to silently simplify the surface.

The primary v1 evidence is commit `fcb7222`, especially
`apps/mobile/CLAUDE.md`, `docs/MOBILE_DESIGN_DECISIONS.md`, and the relevant
feature history. Two important examples show why chronology matters:

- `4896983` restored the intentionally green/red Right/Wrong actions and the
  lower-right context element after an unrelated change had flattened them.
- `8b5ae8b` and its constituent March commits record multiple deliberate Deals
  layout, interaction, search, menu, and overflow polish passes.

## Current explicit product decisions

These decisions supersede conflicting v1 behavior:

- An explicit Submit from a prefilled Confirm or Adjust sheet is a real report
  even when the amount is unchanged. It retains `pricePrefilled = true` and
  `priceTouched = false`; server-side echo protection handles model feedback.
- A committed user cover report is always normalized to the nearest $5.
  Decimal or intermediate values may exist only while editing. Positive
  halfway values round upward, values are bounded to $0...$70, and historical
  source records retain their raw values.
- `$0`, `$5`, `$10`, and `$20` remain the prominent cover quick choices.
- v2 may default new deal timing to **Unknown** rather than v1's **All night**.
  This is a deliberate evidence-semantics change: unknown must not silently
  become a universal timing claim.
- Deal rows within a venue preserve v1's intentional ordering contract: rows
  with admitted same-night evidence come first, newest evidence first; rows
  without such evidence then use a persisted predictor-defined rank; display
  name and stable identity are only deterministic fallbacks. v2 must grow this
  authority in the predictor/server model rather than infer a rank in the
  client from incidental support fields.
- v2 deliberately replaces v1's rendered-screen share image with a designed,
  branded venue share card. The export is its own product surface and need not
  reproduce navigation, Contribute, recent reports, or Right/Wrong controls.
  It still needs a useful venue/cover composition, an IlliniCover link
  fallback, accessibility-safe activity payload, and direct runtime inspection
  of the exported bitmap.

## Bars and cover cards

Intentional v1 baseline:

- The card is a calm, continuous rounded surface (22-point radius and
  16-point horizontal padding in the reference implementation) with three
  visually balanced rows.
- Bar name and cover price lead at equal visual weight; v1 uses 26-point type
  for both. Price must not dominate merely because it sits on the right.
- Evidence/status occupies row two. Row three keeps Right/Wrong on the left and
  a compact source/freshness context marker on the right.
- Right is green and Wrong is red, with icons and labels so color is not the
  only signal. Their resting capsules use a subtle semantic tint and deepen on
  press.
- Card-body presses open details. Embedded Right/Wrong controls never trigger
  the body action or body pressed state.
- Scroll discrimination, immediate press feedback, and non-overlapping
  expanded hit targets are intentional. The implementation may differ from
  v1's Expo hit-halo workaround, but the resulting targets may not overlap.
- A body long press exposes the native menu **Open details**, **Report right
  price**, and **Report wrong price**.
- An ordinary Right tap and the body-menu Right action open Confirm. Only the
  Right control's long-press **Quick confirm** path submits directly.
- An ordinary Wrong tap and the body-menu Wrong action open Adjust. The Wrong
  long-press submenu offers quick `$0`, `$5`, `$10`, and `$20` reports.
- Choosing a Wrong quick amount equal to the currently displayed reporting
  amount opens Adjust rather than performing a contradictory quick action.
  Once that sheet is open, the user's explicit unchanged Submit is still valid
  under the current product decision above.
- The Bars sort menu uses **Open Date (Old-New)**, **Name (A-Z)**, **Lowest by
  Reports**, and **Recently Updated**. Open date is the default; names break
  ties; missing opening years/prices/timestamps sort last. v1's implementation
  defines Recently Updated as the estimate-generation timestamp whenever an
  estimate exists, otherwise the latest live report. Whether v2 should retain
  that estimate-first priority or use the newest admitted public activity is an
  explicit unresolved product decision, not a silent cleanup.

Evidence: `bar-card.tsx`, `bar-card-menu.ts`, `BarsScreen.tsx`,
`use-bar-card-menu-actions.ts`, their tests, and commits `2507c69`, `1bb1ec5`,
`bf83997`, and `4896983`.

## Venue detail

Intentional v1 baseline:

- The header retains compact Navigate and Share actions. Navigate opens walking
  directions to the venue.
- Share captures the rendered detail surface as an image. Its fallback payload
  includes a short message and the IlliniCover venue deep link; sharing only a
  name/address string is not equivalent behavior. This records the v1
  baseline; the explicit branded-card decision above intentionally supersedes
  the captured-screen composition for v2.
- The cover is one continuous 24-point card: `COVER` at upper left, a semantic
  status/help action at upper right, a centered 64-point price, evidence at
  lower left, and an estimate explanation drill-in at lower right.
- Contribute is the primary full-width action below the cover card.
- Recent reports are a grouped preview with a `More Reports` drill-in row, not
  a loose collection of unrelated mini-cards.

Evidence: `BarDetailScreen.tsx`, `bar-cover-card.tsx`,
`useBarDetailScreen.ts`, `share-captured-view.ios.ts`, the clean
`v1-priority-bar-details-kams` runtime triple, and commits `d540b26`,
`1fcecd5`, `5dcba23`, and `83ddb17`.

## Cover report sheet and price editor

Intentional v1 baseline:

- Confirm, Adjust, and direct contribution use the same reporting surface with
  mode-specific title/provenance.
- The sheet opens at a useful standard/middle height, retains Cancel and a
  single Submit action, and can expand for additional content.
- The committed cover control is a large, centered price between circular
  minus/plus actions. v1 uses a 56-point price and a quiet material card.
- Holding minus or plus accelerates repeated $5 changes after an initial
  delay, with bounded haptic feedback. This is a feature, not a one-tap-only
  stepper.
- Tapping the price opens an isolated decimal editor. Partial text never
  changes the committed value. Submit is disabled while editing.
- The editor has explicit Cancel and Done. Cancel restores the committed value;
  Done normalizes to the nearest $5; empty or `.` Done clears cover.
- **Clear / Don't Know** appears before the `$0/$5/$10/$20` quick choices and
  creates no cover observation.
- Above $40, confirmation copy is:
  - title: `Report $X?`
  - message: `That is an unusually high cover. Please double-check that it is $X.`
  - actions: `Cancel` and `Report $X`
- Explicit sheet submission acknowledges receipt without claiming that the
  reporter directly changed the public venue state. Offline persistence needs
  equally honest queued copy.

Evidence: `cover-price-input-card.tsx`, `useReportScreen.ts`,
`confirmHighPrice.ts`, `report-submission.ts`, their presenter/model tests, and
commits `538d769`, `1019b4f`, and `d540b26`.

v2 additions such as vantage point, optional vibes, and one-shot location are
allowed. They must not displace or weaken the established cover-price states,
editor transitions, or primary submission path.

## Deals list, venue sections, and deal rows

Intentional v1 baseline:

- Every active venue remains represented, including venues with no current
  deals; empty venues group after venues with deals.
- Each venue header has a tappable venue name, an inline count capsule, and a
  compact circular plus action with an expanded non-overlapping target.
- Deals sorting is a separate domain from cover sorting. The four labels and
  meanings are:
  - **Open Date (Old-New)**: earliest known venue opening year first;
  - **Name (A-Z)**;
  - **Lowest by Reports**: average of the venue's concrete single-deal prices,
    missing values last;
  - **Recently Updated**: latest admitted deal-evidence activity first.
- A deal card is a 22-point continuous rounded surface with 16-point padding,
  a strict two-row content block on the left, and a dedicated confirm/deny
  action column on the right.
- Row one is fixed-width price, truncating name, then serving. Price never
  auto-shrinks; name truncates before serving. Row two is status plus known
  timing. Unknown timing is omitted on the compact row.
- The body is the primary Edit/Correct target. Confirm and deny remain separate
  44-point semantic circular actions and never trigger body edit.
- Scroll press delay and body/action isolation are deliberate. Long-press menu
  actions are supplementary, not the only way to discover correction.
- Within a venue, visible rows use newest admitted evidence activity first,
  then persisted predictor rank, then display name/stable identity. Prediction
  creation time is not admitted evidence and must not eclipse predictor rank.
  A correction that still belongs to a predicted target retains the target's
  rank unless admitted evidence moves it ahead under the first key.

Evidence: `DealsScreen.tsx`, `deals-section-header.tsx`, `deal-row-card.tsx`,
`deals-format.ts`, their tests, commit `8b5ae8b`, and overflow follow-ups
`5bad79c` and `2b2acfa`.

## Deal composer, menus, and search

Intentional v1 baseline:

- A new deal begins with serving **Each**. Selecting a drink or food serving
  infers category; there is no visible category toggle.
- The denial action is prominent near the top in the dedicated deny flow.
- Deal name and the side-by-side Timing/Serving selectors form one information
  group. The collapsible price card follows that group; it is not the first
  unrelated Form section.
- Serving and timing use sectioned native menus. The observed Serving hierarchy
  is **Each**; a **Drinks** section with Can, Bottle, Pitcher, Shot, Pint, and
  Glass; a **Food** section with Order, Basket, and Plate; then **Other**.
  Custom serving appears only after explicitly choosing Other.
- The observed Timing hierarchy is **All night**, **Until sold out**, and
  **Unknown**, followed by a **Time-specific** section containing Before,
  After, and Between. Those choices present the required native wheel picker or
  pickers in an overlaid popover; they are not flattened into inline form rows.
- Price begins collapsed in review/confirm contexts with quick choices visible.
  Expansion provides exact/range/relative modes, aligned steppers and editor,
  explicit Cancel/Done, and no decorative internal separator.
- Add Deal automatically opens and focuses deal-name search once. Search is a
  contained panel, not an unrelated full workflow.
- The reference search requests and presents up to six results. It highlights
  the matching text without changing measurement, cues the first result, and
  shows price, timing/serving, venue/global scope, last-seen date, and
  alias-match context. Earlier commit prose mentioned three rows, but the final
  source is the later authority for the result count.
- Keyboard Done chooses the first suggestion or commits the trimmed custom
  name. Backdrop/Cancel restores the previously committed name.
- Applying a suggestion keeps its complete distinct shape and briefly flashes
  the fields that changed so the overwrite is legible.

Evidence: `deal-report-form-body.tsx`, `deal-price-input-card.tsx`,
`DealNameCombobox.ios.tsx`, `DealNameComboboxRows.tsx`, their tests, and commits
`526e12e`, `584b1c3`, `9c0ea3c`, `8406a10`, and `8b5ae8b`.

## Implementation workarounds versus product behavior

Known v1 implementation techniques that do not have to be copied include:

- React Native/Expo wrappers used to host native context menus;
- splitting overlapping hit halos at the midpoint;
- View-segment search highlighting used to avoid an iOS attributed-text
  measurement shift;
- asymmetric spacing that compensates for framework text bounding boxes.

The code mechanism may be replaced. The visible spacing, measurement stability,
hit isolation, menu hierarchy, pressed feedback, and keyboard behavior that
the mechanism protected remain acceptance requirements.

## Runtime evidence status

The exact-source v1 Release was rebuilt with valid simulator entitlements and
now launches without the unrelated **Account features are paused** banner.
The bounded v1 run produced 39 clean screenshot, hierarchy, and bounded-log
triples across Bars and Deals in light/dark appearance, card menus, Confirm and
Adjust, editor transitions, high-price confirmation, venue detail, Deals
alerts/review, Add/search, the open Serving and Timing menus, the time wheel,
all three price modes, and actual cover Submit/Quick Confirm/Quick Wrong
receipts. They establish only the v1 half of a comparison.

The remaining v1 runtime gaps are Deal confirm/deny/edit/Add submission
receipts, outer-sheet Cancel/swipe/detent transitions, an engineered empty Deal
section, and post-sort resulting row orders. Source/tests may establish their
intent, but they are not runtime proof. Existing v2 priority captures made with
`PreviewAPIClient` remain rejected; every parity row requires the newest normal
`LiveAPIClient` v2 binary on the same iPhone 16e / iOS 26.5 simulator at the
same navigation depth and interaction state.

## Deliberate v2 extensions and unresolved judgments

The new evidence model, explicit Unknown timing, ranged cover states, offline
receipts, vantage/vibes/location, Time Machine, privacy lifecycle, and account
surfaces may add states that v1 did not have. They do not authorize redesigning
the established states they intersect.

One boundary remains intentionally explicit: historical/model inputs may
retain off-step raw prices, while committed user reports normalize to $5. The
client must preserve the decision identity and the product state actually shown
to the user; it must not silently claim that a different price was displayed.
