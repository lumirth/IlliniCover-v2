# IlliniCover v2 Product and Technical Specification

**Status:** Proposed reference specification
**Product:** IlliniCover
**Primary platform:** iOS
**Future platform:** Android
**Primary market:** UIUC and Champaign-Urbana nightlife
**Core product:** Crowdsourced and predictive bar-cover information

---

## 1. Executive summary

IlliniCover v2 is a native mobile application backed by one conventional server and one relational database.

Its primary purpose is:

> Tell a person the best current estimate of cover at each relevant UIUC bar.

Live community reports are the most valuable evidence. A historical predictor fills gaps when live evidence is absent. A same-night nowcast adjusts future estimates when the current night behaves differently from a normal night.

Drink deals remain a separate first-class domain. They share venues, contributor identity, submission context, and infrastructure with cover. They do not share cover’s predictor, evidence rules, or lifecycle.

The reference architecture is:

```text
iOS app
  SwiftUI
  GRDB / SQLite
  generated OpenAPI client
  RevenueCat
       │
       ▼
one Django application
  Django Ninja API
  django-allauth headless
  cover resolver and predictor
  deal resolver and predictor
  scheduled management commands
  Django Admin
       │
       ▼
PostgreSQL
```

Android will use Kotlin and Jetpack Compose against the same OpenAPI contract.

The client caches server answers and queues offline submissions. The server remains the only place that interprets observations, resolves cover, predicts prices, and evaluates trust.

The most important design rule is:

> **Preserve evidence. Version interpretation. Do not turn a derived conclusion into a new source of truth.**

---

## 2. Normative terms

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** describe requirement strength.

- **MUST:** Required for v2.
- **SHOULD:** Strong recommendation. A deviation needs a concrete reason.
- **MAY:** Optional.
- **Deferred:** Intentionally not decided until evidence justifies a choice.

---

## 3. Product definition

### 3.1 Primary product

IlliniCover is first and foremost a bar-cover application.

A person opens IlliniCover to answer:

- What is cover at each bar now?
- How recent is that information?
- Is the answer based on a live report or historical prediction?
- What have people reported recently?
- What will cover probably be later?
- What was cover probably like at a past time?

Everything else supports that purpose.

### 3.2 Secondary product surfaces

IlliniCover v2 also includes:

- Drink-deal discovery and reporting.
- Vibe observations:
  - line length;
  - line speed;
  - crowd level.
- A handbook or guide surface managed through the backend.
- Optional accounts.
- A paid Time Machine feature.
- Internal administration and model-debugging tools.

### 3.3 Known future possibilities

The architecture SHOULD leave clean seams for:

- Android.
- More bars.
- More contextual data.
- More vibe dimensions.
- Event information.
- Operator or venue integrations.
- Improved cover and deal models.
- Additional premium features.

The architecture MUST NOT build generalized systems for those possibilities before a real feature requires them.

### 3.4 Explicit non-goals

IlliniCover v2 is not:

- a social network;
- a generic nightlife platform;
- a microservice system;
- a real-time messaging system;
- a generic event-sourcing framework;
- an ML platform;
- an automated Instagram-ingestion platform;
- a universal content or fact engine;
- a cross-platform UI framework;
- a client-side prediction system.

---

## 4. Core design principles

### 4.1 Cover is primary

The cover board is the main app surface.

Deals, vibes, and handbook content MUST NOT obscure the core cover experience.

### 4.2 Cover and deals are separate domains

Cover and deals share:

- venues;
- actors;
- accounts;
- submission context;
- common API infrastructure;
- database infrastructure;
- administration.

They do not share:

- predictors;
- truth rules;
- report actions;
- display-state logic;
- historical labels;
- confidence semantics;
- expiry rules.

### 4.3 One main answer

The cover card SHOULD show one main price or range.

The main card MUST NOT normally show two competing headline prices such as:

```text
Live: $20
Predicted: $10
```

That presentation is too easy to misread.

The card SHOULD instead show:

```text
$20
Live
```

or:

```text
$15
Historical
```

Supporting information can appear in the venue detail or recent-report timeline.

### 4.4 Reports are evidence, not truth declarations

A report means:

> A person reported this observation at this time from this context.

It does not mean:

> The database now knows the official cover price.

### 4.5 One ordinary report is useful

One fresh, ordinary cover report SHOULD be sufficient to drive the live cover display.

A report does not need to earn trust through:

- account age;
- sign-in;
- GPS;
- previous reports;
- a reputation score.

Missing positive signals are neutral.

The system SHOULD reduce or reject evidence only when it has an affirmative reason to distrust it.

### 4.6 Preserve raw evidence

The system SHOULD preserve:

- original report value;
- exact observation time;
- exact submission time;
- raw location and accuracy when supplied;
- product state shown to the reporter;
- report interaction path;
- actor and installation context;
- raw imported historical data;
- source provenance;
- model and code revisions.

Derived classifications MAY be recomputed later.

### 4.7 Server owns interpretation

The clients MUST NOT independently:

- resolve current cover;
- calculate trust;
- train or run the cover predictor;
- calculate the same-night nowcast;
- resolve deal evidence;
- reconstruct Time Machine results.

The client displays server decisions and caches them.

### 4.8 No speculative infrastructure

The initial v2 system MUST NOT require:

- Redis;
- Celery;
- Kafka;
- Temporal;
- Kubernetes;
- GraphQL;
- WebSockets;
- a separate model service;
- a separate admin application;
- a general synchronization engine;
- an object-storage service unless a real feature needs one.

---

## 5. Product surfaces

## 5.1 Cover board

The cover board is the default app screen.

Each active venue card SHOULD show:

- venue name;
- main cover price or range;
- source label;
- freshness;
- a compact status;
- report affordances.

Example:

```text
KAMS

$20
Live · 8 min ago
```

or:

```text
Brothers

$10
Historical
```

The board SHOULD remain quick to scan while intoxicated, distracted, or outside in poor lighting.

### 5.1.1 Cover states

The product-level states are:

- **Live:** Admitted current reports determine the answer.
- **Historical:** The historical predictor and same-night nowcast determine the answer.
- **Mixed:** Multiple current prices remain materially plausible.
- **Unconfirmed or unusual:** Current evidence exists, but an affirmative trust concern affects presentation.
- **Unavailable:** The system has no useful answer.

Exact copy MAY retain established language such as “Live,” “Historical,” “Usually,” or “Typically” after UX testing.

The user interface SHOULD communicate uncertainty through source, freshness, and recent reports. It SHOULD NOT display statistical warnings for ordinary sparse data.

## 5.2 Venue detail

The venue detail SHOULD include:

- current cover decision;
- source and freshness;
- recent cover reports;
- recent vibe observations;
- current or likely deals;
- basic venue information;
- Time Machine entry point;
- report action.

The detail view MAY show the historical baseline as secondary context when:

- the live evidence is thin;
- current reports conflict;
- a report is marked unusual;
- the user explicitly opens more detail.

## 5.3 Cover reporting

The existing interaction pattern SHOULD be preserved unless native implementation testing proves a better design.

The flow includes:

- “correct” and “wrong” entry actions that open the same reporting interface;
- a fast confirmation path;
- long-press quick reporting where appropriate;
- a “don’t know” cover option;
- optional vibe input;
- optional location;
- a single clear submission action.

A user MUST be able to submit:

- cover only;
- vibes only;
- cover and vibes together.

At least one real observation is required.

“Don’t know cover” is UI state. It does not create a cover observation.

### 5.3.1 Immediate feedback

There is no universal publication delay.

The app SHOULD acknowledge:

> Report received.

It SHOULD NOT say:

> You changed KAMS to $20.

The server can immediately resolve the new cover state. The client MAY refresh the card normally.

This preserves freshness without giving a troll an exaggerated sense of direct control.

## 5.4 Recent reports

Free users SHOULD be able to inspect recent reports for the current service night.

The timeline SHOULD show enough evidence for users to judge the state themselves, such as:

- reported price;
- age of report;
- source label where relevant;
- broad location context if safe;
- vibe tags;
- whether reports changed over time.

The public timeline MUST NOT expose:

- exact coordinates;
- actor identifiers;
- account identifiers;
- device metadata;
- IP or network metadata;
- internal suspicion reasons.

## 5.5 Time Machine

Time Machine is a premium feature.

It answers:

> What is IlliniCover’s best current reconstruction or prediction for this venue at this time?

It supports:

- past times;
- current time;
- future times.

The UI SHOULD use a clear date/time selector or timeline.

It MUST NOT imply that a reconstructed historical price is an official archived fact.

### 5.5.1 Past

For a past time, Time Machine uses:

- reports near that time;
- reports later in the same service night;
- admitted historical evidence;
- the historical model;
- relevant preserved context;
- retrospective price-path inference.

The result is the best reconstruction available now.

The initial supported window is ten years into the past and one year into the
future. Targets within 60 seconds of the server knowledge cutoff are one
`current` mode and snap to that cutoff; the server returns the authoritative
`past`, `current`, or `future` mode. Served receipts are minute-granular and
reused, and account/network read limits bound abuse without changing access to
ordinary premium use.

This is different from:

> What did the old model display at that moment?

The old as-of decision remains available internally for debugging and evaluation.

### 5.5.2 Future

For a future time, Time Machine uses:

- the current production model release;
- known future context;
- venue pattern;
- campus pattern;
- same-night nowcast when the target is in the active service night.

### 5.5.3 Free versus premium history

Initial product policy:

- Free:
  - current cover;
  - recent current-night reports;
  - limited recent history.
- Premium:
  - arbitrary supported past queries;
  - future cover predictions;
  - extended report history;
  - full Time Machine.

Exact free-history limits MAY be adjusted as a product decision.

The v2 launch policy is seven service nights and at most 50 public reports per
venue for Free. Premium extends the same admission-filtered, privacy-minimized
timeline to 90 service nights and at most 250 public reports per venue. The API
reports the applied tier and window start. Its `hasMore` flag means that more
admitted reports exist inside that applied window than the tier's result cap;
the window start itself is the honest boundary for older history. Premium never
expands the fields exposed for a report.

## 5.6 Deals

Deals remain a separate top-level surface.

The deals view SHOULD present a nightly slate by venue.

It MAY support a specific target time.

A venue with no visible deals SHOULD remain discoverable and reportable.

## 5.7 Handbook

The handbook is a separate content surface.

It MAY contain:

- venue guides;
- etiquette;
- definitions;
- cover explanations;
- campus-nightlife information;
- safety information;
- product help.

It is managed through Django Admin.

It does not participate in cover or deal prediction.

---

## 6. System architecture

```text
┌────────────────────────────────────┐
│ iOS                                │
│ SwiftUI                            │
│ GRDB / SQLite cache + outbox       │
│ generated OpenAPI client           │
│ RevenueCat                         │
└─────────────────┬──────────────────┘
                  │ HTTPS / JSON
                  ▼
┌────────────────────────────────────┐
│ One Django application             │
│                                    │
│ Django Ninja API                   │
│ django-allauth headless            │
│ cover resolver                     │
│ historical predictor               │
│ same-night nowcast                 │
│ deal resolver and predictor        │
│ Time Machine                       │
│ RevenueCat webhook handling        │
│ Django Admin                       │
│ management commands                │
└─────────────────┬──────────────────┘
                  │ Django ORM
                  ▼
┌────────────────────────────────────┐
│ PostgreSQL                         │
│ durable observations              │
│ model releases                     │
│ source/context data                │
│ decision receipts                  │
│ accounts and actors                │
└────────────────────────────────────┘
```

### 6.1 One backend boundary

All app data MUST go through the Django API.

The clients MUST NOT connect directly to PostgreSQL.

There is no endpoint-per-deployment-unit architecture.

### 6.2 One deployable backend

The backend is one codebase and one deployable image.

The same image runs as:

- a web process;
- scheduled management commands.

### 6.3 Request-time resolution

Cover and deal answers SHOULD initially be computed when requested.

The system MAY cache results after measurement shows a useful benefit.

The system SHOULD precompute only naturally batch-oriented outputs, such as:

- trained model parameters;
- normalized context;
- deal predictor state;
- dataset import products.

---

## 7. Reference technology stack

| Area | Choice |
|---|---|
| iOS language | Swift |
| iOS UI | SwiftUI |
| iOS state | Observation and structured concurrency |
| iOS local database | SQLite through GRDB |
| iOS API client | Apple Swift OpenAPI Generator |
| Android language | Kotlin |
| Android UI | Jetpack Compose |
| Backend language | Python |
| Backend framework | Django |
| API framework | Django Ninja |
| Authentication | django-allauth headless |
| Database | PostgreSQL |
| Background work | Django management commands and ordinary scheduler |
| Internal admin | Django Admin |
| Billing | RevenueCat |
| API contract | OpenAPI |
| Repository | Monorepo |

Django Ninja is used because it declares typed request and response schemas and generates an OpenAPI schema from the API operations.

django-allauth headless is designed for mobile and single-page applications, and its account configuration supports login by a one-time emailed code.

GRDB provides explicit SQLite access, migrations, concurrency support, and observation without creating a separate sync architecture.

Swift OpenAPI Generator generates a typed Swift client at build time from an OpenAPI document and supports a `URLSession` transport.

RevenueCat custom App User IDs allow the same IlliniCover account to receive the same entitlement on multiple devices and platforms.

Django Admin is intentionally suited to trusted internal, model-centric management rather than the public application.

Django management commands are suitable for standalone and periodically scheduled work.

---

## 8. Terminology

### 8.1 Venue

The internal term is **venue**.

The user-facing app MAY say **bar**.

### 8.2 Service night

A service night groups nightlife activity across midnight.

IlliniCover uses:

- time zone: `America/Chicago`;
- service-night cutoff: 5:00 AM.

For example:

- Saturday at 1:30 AM belongs to Friday’s service night.

The cutoff is bookkeeping. It does not assert venue operating hours. The current system already uses this distinction and keeps original observation time separate from service-night fields.

### 8.3 Installation actor

A persistent pseudonymous identity for one app installation.

It is not an account.

### 8.4 Account

An optional user identity authenticated by verified email code.

### 8.5 Submission

One user interaction that tells IlliniCover something about a venue.

### 8.6 Observation

A typed fact supplied inside a submission.

Examples:

- cover price;
- line length;
- crowd level.

### 8.7 Decision

A derived answer produced by IlliniCover.

A decision is not raw evidence.

### 8.8 Historical model

The long-term predictor trained on admitted observations from completed service nights.

### 8.9 Same-night nowcast

A temporary adjustment based on how the current service night differs from historical expectations.

### 8.10 Knowledge cutoff

The latest time from which evidence is allowed when computing a decision.

---

## 9. Shared submission model

### 9.1 Submission envelope

All user contributions share a small common envelope.

Conceptual fields:

```text
submission
  id
  actor_id
  authenticated_account_id nullable
  venue_id
  observed_at_client
  received_at_server
  time_quality
  vantage_point
  latitude nullable
  longitude nullable
  location_accuracy_m nullable
  location_permission
  client_platform
  client_version
  entry_point
  idempotency_key
  created_at
```

The submission envelope records context.

It does not interpret that context.

Cover, vibes, and deals decide separately what location, account status, and actor history mean.

### 9.2 Immutability

An accepted submission MUST be immutable.

A correction creates new evidence.

The system MUST NOT silently rewrite historical observations.

### 9.3 Observation time and upload time

The system stores both:

- **observed time:** when the user says they observed the condition;
- **received time:** when the server accepted the submission.

Offline reports use observed time for freshness and history.

A report observed at 11:05 PM and uploaded at 11:12 PM can still be live.

A report observed at 11:05 PM and uploaded at 1:00 AM remains historical evidence but MUST NOT appear as a fresh 1:00 AM report.

### 9.4 Client-clock quality

The backend SHOULD validate client observation time.

It SHOULD record a quality state when:

- the client time is far in the future;
- the client time is implausibly old for the interaction;
- the device clock appears significantly wrong.

A poor time-quality report MAY remain stored but receive less live weight.

### 9.5 At-least-one rule

A submission MUST contain at least one typed child observation or evidence event.

Examples:

- cover only;
- one vibe only;
- cover plus several vibes;
- one deal evidence event.

---

## 10. Installation actors and accounts

## 10.1 Guest use

Browsing does not require an account.

Reporting does not require an account.

On first use that requires persistent identity, the app obtains an installation actor credential.

Conceptual flow:

```text
app install
   ↓
installation actor
   ↓
guest reporting
```

The credential is stored in Keychain on iOS.

The server stores only a secure verifier or token hash.

### 10.1.1 No invasive fingerprinting

The initial system SHOULD use:

- installation credential;
- rate limits;
- server-observed request patterns;
- optional location;
- actor behavior.

It SHOULD NOT begin with invasive hardware or advertising fingerprinting.

Platform attestation MAY be added later if real abuse justifies it.

## 10.2 Account authentication

Initial v2 authentication is:

> Any verified email plus a one-time code.

There are no passwords.

There is no UIUC-only requirement.

There is no Sign in with Apple initially.

### 10.2.1 Email as credential

Email is a credential, not the account’s primary key.

The account has a stable internal UUID.

Changing email MUST NOT change:

- account ID;
- premium entitlement;
- linked actors;
- preferences;
- report associations.

## 10.3 Actor-account links

When a guest signs in:

```text
installation actor A
       │
       └── linked to account X
```

Reports remain attached to actor A.

They are not moved or rewritten.

A second device creates actor B:

```text
account X
  ├── actor A
  └── actor B
```

### 10.3.1 Trust implication

Signed-in status is a small positive signal.

It is not dominant.

A mature guest actor with a coherent history can be more useful than a new signed-in account.

## 10.4 Sessions

Mobile session tokens are stored in Keychain.

Session lifetime SHOULD be long enough that optional accounts do not create repeated friction.

Sensitive account actions MAY require a fresh email code.

## 10.5 Account deletion

Account deletion MUST remove:

- account credentials;
- sessions;
- actor-account links;
- premium mirror state;
- private profile and preferences;
- account-specific metadata.

For linked actor contributions, the deletion process MUST remove or deidentify personally linked material according to the published privacy policy.

At minimum:

- stable account linkage is removed;
- exact network metadata is removed;
- exact location is removed when the contribution must be deidentified;
- no stable deleted-user pseudonym remains.

The system MAY retain a deidentified observation value such as:

```text
KAMS
$20
11:05 PM
```

only when the result cannot reasonably be tied back to the deleted person.

Guest users SHOULD have a way to delete or rotate the current installation actor and its private data.

---

## 11. Cover-observation model

Conceptual fields:

```text
cover_observation
  id
  submission_id
  reported_price_cents
  interaction_kind
  displayed_decision_id nullable
  displayed_source
  displayed_price_kind
  displayed_price_cents nullable
  displayed_price_low_cents nullable
  displayed_price_high_cents nullable
  price_prefilled
  price_touched
  created_at
```

### 11.1 Price representation

Cover is stored in integer cents.

New user-submitted cover observations MUST be committed and accepted in $5
increments. Manual entry MAY contain an intermediate decimal draft while the
person is editing, but Done rounds it to the nearest $5 before the value is
displayed as committed or submitted. Historical source records retain their
original raw values for provenance and model evaluation.

Free entry is represented as `$0`.

“Don’t know” creates no cover observation.

### 11.2 Interaction kinds

Examples:

- `confirm`;
- `correct`;
- `direct`;
- `quick_confirm`;
- `manual`.

The interaction kind is evidence about how the user produced the value.

### 11.3 Preserve displayed context

The system MUST preserve the semantic product state the user saw.

These are not equivalent:

```text
The app showed $20.
The user confirmed $20 without touching it.
```

and:

```text
The app showed $10.
The user manually changed it to $20.
```

The current implementation already records displayed source, displayed estimate identity, prefill state, touch state, entry path, location, and device context. That provenance should survive v2 even though the architecture around it changes.

An explicit Submit from the Confirm or Adjust interface creates a cover
observation even when the prefilled amount was not changed. In that case the
original displayed decision, `price_prefilled = true`, and
`price_touched = false` distinguish the report from a manually changed price.
The resolver's model-echo protection below still applies; the client MUST NOT
discard the person's explicit report merely because its amount is unchanged.

### 11.4 Model-echo protection

A single untouched confirmation of the app’s own historical estimate MUST NOT become a new independent price label for training.

It also SHOULD NOT by itself relabel the card as live when it merely repeats the exact model suggestion.

Two or more independent confirmations MAY establish current live evidence.

The current implementation already protects against a singleton untouched estimate echo and admits it only after independent corroboration.

---

## 12. Vibe-observation model

Vibes are structured dimensions presented as simple UI tags.

Conceptual fields:

```text
vibe_observation
  id
  submission_id
  dimension
  value
  created_at
```

A submission can contain at most one value for each dimension.

### 12.1 Initial dimensions

#### Line length

```text
short
medium
long
```

#### Line speed

```text
slow
normal
fast
```

#### Crowd level

```text
quiet
busy
packed
```

### 12.2 Presentation

The UI MAY render structured observations as natural tags:

```text
line_length = long
```

becomes:

```text
Long line
```

### 12.3 Progressive disclosure

The reporting UI SHOULD ask only relevant questions.

Examples:

- Outside:
  - line length;
  - line speed.
- Inside:
  - crowd level.

This is presentation logic. The server MAY accept valid observations even when the reported vantage point is unknown.

### 12.4 Independent freshness

Each vibe dimension MAY have its own freshness rule.

For example:

- line length can change quickly;
- crowd level may remain useful longer.

Those rules MUST NOT be coupled to cover freshness merely because the observations arrived in one submission.

---

## 13. Trust and evidence assessment

## 13.1 No permanent user trust score

The system MUST NOT reduce a person to one permanent score such as:

```text
trust_score = 73
```

The resolver assesses each observation in context.

### 13.2 Inputs

Evidence assessment MAY use:

#### Observation signals

- age of report;
- observation-time quality;
- location and accuracy;
- distance from venue;
- whether value was manually changed;
- whether it echoed an existing prediction;
- interaction path.

#### Actor signals

- installation age;
- previous report count;
- previous corroboration;
- history of coherent reporting;
- rapid contradictory patterns;
- sign-in status.

#### Abuse signals

- multiple accounts linked through one installation;
- impossible movement;
- repeated contradictory submissions;
- rate-limit evasion;
- automation patterns;
- abnormal network clustering;
- coordinated actor behavior.

The current system already uses actor deduplication and concrete abuse detectors such as multiple accounts linked through a device and impossible presence across venues.

### 13.3 Neutral missing data

The following are neutral by default:

- guest status;
- no location;
- new installation;
- no report history;
- no verified affiliation.

### 13.4 Positive signals

Examples:

- accurate nearby location;
- mature coherent actor history;
- independent corroboration;
- manual correction of a different displayed value;
- signed-in account.

### 13.5 Negative signals

Examples:

- impossible movement;
- linked-account vote stuffing;
- rapid spam;
- known automation;
- repeated obviously contradictory patterns;
- severe clock manipulation.

### 13.6 Admission classes

The internal system SHOULD distinguish:

- **admitted normally;**
- **admitted with reduced weight;**
- **excluded from public state but retained for audit;**
- **rejected at submission because of abuse or invalidity.**

The public UI MUST NOT expose internal abuse reasons.

---

## 14. Live cover resolution

## 14.1 Current cover is derived

The database MUST NOT treat:

```text
venue.current_cover = $20
```

as durable truth.

The system stores evidence and derives the current answer.

A cached answer is a projection, not a source of truth.

## 14.2 Conceptual resolver

```text
resolve_cover(
  venue,
  target_time,
  knowledge_cutoff,
  model_release
)
```

Inputs include:

- admitted cover observations;
- historical predictor;
- same-night nowcast;
- campus-wide nowcast;
- validated direct admission facts;
- context;
- resolver version.

Output includes:

- main price or range;
- source;
- freshness;
- decision ID;
- recent report summary;
- internal support details.

## 14.3 Live evidence priority

Admitted fresh live observations normally override the historical prediction in the main display.

The current app already follows this broad rule: live evidence produces `LIVE_ACTIVE`, `LIVE_MIXED`, or `LIVE_SUSPICIOUS`; otherwise it falls back to a model estimate.

## 14.4 One-report rule

One ordinary manual report can establish a live state.

Exceptions include:

- untouched echo of the historical estimate;
- hard abuse evidence;
- invalid timestamp;
- invalid price;
- severe identity manipulation.

## 14.5 Recency

Live evidence weight SHOULD decay with age.

A configurable live horizon MAY initially remain near the current 60-minute behavior, but the number MUST NOT be embedded into the schema.

The resolver SHOULD prefer continuous recency weighting over a simple fresh/dead cliff where practical.

## 14.6 Conflicting reports

A disagreement does not automatically require a range.

The resolver SHOULD consider:

- report order;
- recency;
- actor independence;
- evidence quality;
- whether a coherent newer cluster replaced an older cluster;
- venue’s usual price-change behavior.

A range SHOULD appear only when multiple current prices remain materially plausible.

## 14.7 Time-varying price model

Internally, cover SHOULD be treated as a price that can change through the service night.

Reports are imperfect observations of that changing price.

A reference implementation MAY use a small discrete state model:

- possible states: `$0`, `$5`, `$10`, `$15`, and so on;
- price usually remains stable between nearby times;
- price can change when evidence supports it;
- unnecessary changes receive a penalty;
- report quality affects observation weight.

This model can support:

- current online filtering;
- retrospective Time Machine smoothing;
- identification of likely price changes;
- rejection of isolated outliers.

The user-facing app still shows a decisive answer.

---

## 15. Historical cover predictor

## 15.1 Training source

The historical predictor MUST train on admitted observations.

It MUST NOT train on the Time Machine’s reconstructed price path as if that reconstruction were ground truth.

Pipeline:

```text
raw observations
      ↓
actor deduplication
      ↓
provenance and evidence weighting
      ↓
historical predictor
```

## 15.2 Completed service nights

Current-night reports can affect:

- live state immediately;
- same-night nowcast immediately.

They SHOULD enter long-term historical training only after the service night is complete.

This prevents constant online retraining and keeps the historical model stable during a night.

## 15.3 Continuous time

Clock time is a real ordered feature.

Hard blocks such as:

```text
BEFORE_9
9_TO_11
AFTER_11
```

MAY be used as sparse fallbacks.

They MUST NOT define the product’s fundamental time model.

The predictor should naturally answer times such as:

- 10:12 PM;
- 10:43 PM;
- 11:17 PM;
- 12:26 AM.

## 15.4 Partial pooling across venues

Each venue has distinct behavior.

Sparse venues can borrow weakly from campus-wide patterns.

Conceptually:

```text
campus pattern
      +
venue pattern
      +
weekday and time
      +
validated context
      ↓
historical prediction
```

As a venue gains data, its own observations dominate.

## 15.5 No manual archetypes

The initial model MUST NOT require hand-authored categories such as:

- party bar;
- sports bar;
- cocktail bar;
- cheap bar.

Behavioral similarity should emerge from data.

Venue ownership MUST NOT initially be encoded as a predictive requirement.

## 15.6 Predictor output

The internal predictor SHOULD produce:

- point or modal price;
- likely range;
- probability of no cover;
- probability of high cover;
- support;
- model release;
- reason information for debugging.

The main UI can still show one price.

## 15.7 Model selection

The spec does not force one model library.

The initial production candidate MUST support:

- continuous time;
- venue-specific behavior;
- campus-level pooling;
- sparse data;
- chronological evaluation;
- calibrated predictions.

A hierarchical statistical model is the reference direction.

Simpler or different challengers MAY be used if they perform better.

---

## 16. Same-night nowcast

## 16.1 Purpose

The nowcast answers:

> Is this service night running hotter or colder than the historical model expected?

It does not retrain the historical model.

## 16.2 Venue adjustment

For each venue, admitted same-night observations can produce a temporary residual:

```text
reported price
-
historical expected price at observation time
=
same-night evidence
```

The adjustment:

- is shrunk when evidence is sparse;
- strengthens with independent corroboration;
- decays as evidence ages;
- is reduced by trust concerns;
- expires with the service night.

## 16.3 Campus adjustment

A smaller campus-wide adjustment combines residual evidence across venues.

Example:

```text
KAMS is above expectation
Lion is above expectation
       ↓
campus night may be hotter than normal
```

This MAY modestly affect venues with no own live evidence.

Venue-specific evidence always dominates.

## 16.4 No pairwise bar graph initially

The initial nowcast MUST NOT build a matrix such as:

```text
KAMS correlates 0.71 with Lion
```

Sparse data makes that too easy to overfit.

A single campus-wide night factor is sufficient until evaluation proves otherwise.

## 16.5 Display behavior

The nowcast affects historical estimates.

It does not need a separate public label.

The user sees the improved prediction.

Internal decision receipts preserve the adjustment.

---

## 17. Context and enrichment

## 17.1 Preserve rich context

The system SHOULD preserve useful context such as:

- weather;
- academic calendar;
- school breaks;
- football and major sports events;
- Homecoming;
- family weekends;
- Unofficial;
- Halloween;
- Thanksgiving Eve;
- venue-specific events;
- validated advertised admission;
- line and crowd observations;
- campus-wide same-night behavior.

## 17.2 Context does not automatically become a feature

The pipeline is:

```text
collect
   ↓
preserve with provenance
   ↓
join to historical outcomes
   ↓
evaluate chronologically
   ↓
admit only if useful
```

A plausible story is not enough.

For example:

- rain may reduce attendance;
- rain may concentrate people into fewer bars.

The model must earn the feature through real predictive improvement.

The current cover model already follows this discipline by treating most unvalidated context as uncertainty information rather than a directional price shift.

## 17.3 Direct admission facts

A current, qualified, unconditional advertised cover can directly inform the displayed answer.

Conditional facts MUST retain their scope.

Examples that MUST NOT become a universal cover:

- “$10 for 21+”;
- “free before 9”;
- “free for women”;
- “ticket holders only”;
- “with wristband.”

## 17.4 Context storage

Context SHOULD use typed tables or typed models.

Examples:

- academic periods;
- sports events;
- weather observations and forecasts;
- venue events;
- tradition dates;
- advertised admission facts.

The system MUST NOT use one universal EAV table such as:

```text
subject
predicate
value_json
```

for all product data.

## 17.5 Source provenance

External context SHOULD reference a source record containing:

- source identifier;
- fetched time;
- source URL or external key;
- raw payload or payload hash;
- parser/importer version;
- status;
- errors.

## 17.6 Automated social extraction

Automated social-media scraping, OCR, or multimodal extraction is not part of the v2 core architecture.

It MAY later become one source adapter.

The cover and deal systems consume typed evidence. They do not depend on how that evidence was acquired.

---

## 18. Time Machine computation

## 18.1 One conceptual function

```text
cover_at(
  venue,
  target_time,
  knowledge_cutoff
)
```

### Current

```text
target_time = now
knowledge_cutoff = now
```

### Future

```text
target_time = future time
knowledge_cutoff = now
```

### Retrospective Time Machine

```text
target_time = past time
knowledge_cutoff = now
```

### Historical model evaluation

```text
target_time = past time
knowledge_cutoff = the historical prediction time
```

## 18.2 Retrospective reconstruction

Time Machine MAY use evidence that arrived after the target time.

Example:

- At 10:30 PM, one report said `$30`.
- Later reports strongly supported `$10`.

The real-time app may reasonably have displayed `$30` at 10:30.

The retrospective Time Machine may later reconstruct `$10`.

Both can be correct relative to their knowledge cutoffs.

## 18.3 Preserve as-of decisions

The system MUST retain enough information to reproduce what the app decided with the evidence available at the original time.

That is an internal debugging and evaluation capability.

It is not the default Time Machine product answer.

---

## 19. Decision receipts

## 19.1 Purpose

Every externally served cover answer MUST have a compact decision ID.

A support report can include:

```text
decision_id = cover_decision_...
```

## 19.2 Decision fields

Conceptual fields:

```text
cover_decision
  id
  venue_id
  target_time
  knowledge_cutoff
  computed_at
  result_price_kind
  result_price
  result_low
  result_high
  source
  model_release_id
  evidence_revision
  context_revision
  resolver_version
  same_night_adjustment_summary
  campus_adjustment_summary
```

## 19.3 Deduplication

The system does not need one row per screen impression.

A decision receipt MAY be reused while all relevant inputs remain unchanged.

## 19.4 Not truth

A decision receipt means:

> This is what IlliniCover decided from these inputs.

It does not mean:

> This was the official real-world price.

---

## 20. Model releases and challengers

## 20.1 Model release

Conceptual fields:

```text
cover_model_release
  id
  model_kind
  model_version
  code_revision
  training_data_revision
  context_feature_revision
  parameters_or_artifact
  evaluation_metrics
  created_at
  promoted_at nullable
  retired_at nullable
```

## 20.2 One authoritative model

Exactly one cover model release is authoritative at a time.

Users receive one production answer.

## 20.3 Shadow challengers

Challenger models MAY run against real production situations.

Their answers are stored for evaluation only.

They MUST NOT:

- affect the user-visible price;
- increase user-request latency if expensive;
- create competing UI outputs.

## 20.4 Promotion

A challenger becomes authoritative only after it wins a defined evaluation.

Promotion MUST be explicit.

The old model SHOULD remain reproducible after retirement.

A retired release identity MUST NOT be promoted again. Model rollback means
issuing a new immutable release that reproduces the desired prior behavior,
evaluating that candidate against the current incumbent with a fresh receipt,
and explicitly promoting the new identity. This preserves the original
promotion and retirement interval as provenance.

## 20.5 Evaluation

Evaluation MUST use chronological splits.

It SHOULD include:

- price MAE;
- zero-cover calibration;
- Brier score;
- likely-range coverage;
- interval width and interval score;
- venue-level slices;
- time-of-night slices;
- special-event slices;
- sparse-data performance;
- same-night nowcast value;
- final untouched holdout;
- post-launch shadow performance.

Random train/test splits MUST NOT be the main quality claim.

---

## 21. Deals domain

## 21.1 Separate predictor

Deals are predictive, but not in the same way as cover.

The deal predictor MUST be selected after analysis of the actual historical deal dataset.

It may involve:

- recurrence;
- schedule regularity;
- venue-specific patterns;
- recent confirmations;
- denials;
- seasonal changes;
- offer lineage;
- deal identity.

The cover predictor MUST NOT be reused merely for consistency.

## 21.2 Deal entity

A concrete deal includes:

```text
category
canonical family
display name
price kind
price or discount
unit
serving format
timing
while-supplies-last
venue
```

Different timings, servings, or prices remain distinct offers.

## 21.3 Deal evidence actions

Initial actions remain:

- `ADD_MISSING`;
- `CONFIRM_PRESENT`;
- `DENY_PRESENT`;
- `CORRECT`.

These match the useful semantics in the existing implementation.

## 21.4 Non-destructive evidence

A denial is evidence that an offer may not be active.

It does not erase historical evidence.

A correction creates a new state or revision while preserving lineage.

## 21.5 Canonical identity

The system SHOULD maintain:

- canonical deal families;
- explicit aliases;
- unresolved custom entries.

Aliases are explicit data.

The system MUST NOT silently invent canonical identities from approximate text similarity in the critical reporting path.

Until the product has a complete moderation, reporting, and abusive-user
blocking workflow, user-authored deal text MUST remain preserved non-public
evidence. A public deal overlay MAY use a server-resolved canonical label or
copy already present on a trusted public target together with constrained
numeric, enum, and boolean corrections. An unresolved custom entry MUST NOT
become public merely because another contributor repeats or confirms it.

## 21.6 Unknown timing

Unknown timing means unknown.

It MUST NOT be treated as “all night.”

## 21.7 Deal prediction analysis milestone

Before v2 finalizes the production deal predictor, the team MUST perform a dedicated analysis of:

- recurrence by weekday;
- timing stability;
- price stability;
- venue-level changes;
- seasonality;
- evidence sparsity;
- identity ambiguity;
- confirmation and denial behavior.

The analysis produces a written model-selection receipt.

---

## 22. Deal evidence model

Deal evidence shares the submission envelope.

Conceptual fields:

```text
deal_evidence_event
  id
  submission_id
  action
  target_deal_id nullable
  target_prediction_id nullable
  submitted_deal_shape nullable
  service_date_local
  target_local_datetime nullable
  created_at
```

The current system already distinguishes add, confirm, deny, and correct actions and carries full deal shape when needed.

Cover and deal evidence can use common actor and abuse history.

Their domain resolvers remain separate.

---

## 23. Handbook and CMS

## 23.1 Initial implementation

Use Django Admin.

Conceptual page fields:

```text
handbook_page
  id
  slug
  title
  summary
  body_markdown
  status
  sort_order
  published_at
  updated_at
```

## 23.2 API

The API serves published handbook content only.

Clients cache handbook pages locally.

## 23.3 Deferred editorial system

Wagtail or a custom editor is deferred.

Add one only when the actual editorial workflow exceeds Django Admin.

---

## 24. API specification

## 24.1 API style

The API is product-shaped REST.

It MUST NOT expose database-shaped CRUD as the primary client contract.

Django Ninja schemas define the OpenAPI contract. Django Ninja validates typed inputs and generates OpenAPI from the declared operations.

## 24.2 Versioning

Initial base path:

```text
/api/v2/
```

Breaking contract changes require a new API version or a compatible migration period.

## 24.3 Core endpoints

### Installation

```text
POST /api/v2/installations
POST /api/v2/installations/rotate
```

### Cover

```text
GET  /api/v2/cover
GET  /api/v2/venues/{venue}/cover
GET  /api/v2/venues/{venue}/cover/history
GET  /api/v2/venues/{venue}/cover/time-machine
POST /api/v2/cover-submissions
```

### Deals

```text
GET  /api/v2/deals
GET  /api/v2/venues/{venue}/deals
POST /api/v2/deal-evidence
```

### Handbook

```text
GET /api/v2/handbook
GET /api/v2/handbook/{slug}
```

### Account

```text
GET    /api/v2/me
DELETE /api/v2/me
POST   /api/v2/me/link-installation
```

Authentication endpoints are provided through django-allauth headless.

### Billing

```text
GET  /api/v2/me/entitlements
POST /api/v2/billing/revenuecat-webhook
```

## 24.4 Cover-board response

Conceptual response:

```json
{
  "serviceDate": "2026-08-12",
  "generatedAt": "2026-08-13T03:15:00Z",
  "venues": [
    {
      "venue": {
        "id": "uuid",
        "slug": "kams",
        "name": "KAMS"
      },
      "cover": {
        "price": {
          "kind": "single",
          "amountCents": 2000
        },
        "source": "live",
        "freshnessSeconds": 480,
        "decisionId": "uuid",
        "status": "live"
      },
      "recentReportCount": 2,
      "vibes": {
        "lineLength": "long",
        "lineSpeed": "fast",
        "crowdLevel": null
      }
    }
  ]
}
```

## 24.5 Cover submission

Conceptual request:

```json
{
  "submissionId": "uuid",
  "venueId": "uuid",
  "observedAt": "2026-08-13T03:07:00Z",
  "vantagePoint": "outside",
  "location": {
    "latitude": 40.0,
    "longitude": -88.0,
    "accuracyMeters": 12
  },
  "cover": {
    "priceCents": 2000,
    "interaction": "correct",
    "displayedDecisionId": "uuid",
    "pricePrefilled": true,
    "priceTouched": true
  },
  "vibes": [
    {
      "dimension": "line_length",
      "value": "long"
    },
    {
      "dimension": "line_speed",
      "value": "fast"
    }
  ]
}
```

The request is atomic.

## 24.6 Idempotency

All write requests MUST include a client-generated idempotency key or submission UUID.

A retry MUST return the original accepted result.

## 24.7 HTTP caching

Read endpoints SHOULD support:

- ETag;
- `If-None-Match`;
- server revision;
- cache timestamps.

The client MUST preserve the original data freshness when rendering cached content.

## 24.8 Error shape

The API SHOULD use one consistent typed error shape:

```json
{
  "code": "rate_limited",
  "message": "Too many reports were submitted.",
  "requestId": "uuid"
}
```

---

## 25. OpenAPI and generated clients

The OpenAPI document is generated from Django Ninja and checked into:

```text
api/openapi.json
```

CI MUST fail when server changes produce an unexplained contract diff.

The iOS app uses Swift OpenAPI Generator. Its build-time generated client stays synchronized with the contract and does not need committed generated source.

Android will generate its client from the same contract.

Client-specific convenience layers MAY wrap generated operations.

They MUST NOT recreate server domain logic.

---

## 26. iOS application

## 26.1 Core stack

- Swift;
- SwiftUI;
- Observation;
- Swift structured concurrency;
- Foundation;
- generated OpenAPI client;
- GRDB;
- RevenueCat;
- Keychain;
- OSLog;
- XCTest and Swift Testing.

## 26.2 Architecture

Use feature-focused native code.

Suggested structure:

```text
ios/
  IlliniCover/
    App/
    Cover/
    Reporting/
    Deals/
    Vibes/
    TimeMachine/
    Handbook/
    Account/
    Billing/
    API/
    Database/
    DesignSystem/
```

The app MUST NOT reproduce:

- Redux;
- TCA;
- presenter layers;
- route metadata files;
- platform contract layers;
- repository protocols around every endpoint;
- a generic dependency-injection framework.

A small explicit application environment is acceptable.

## 26.3 State

Feature models use `@Observable`.

Example:

```swift
@Observable
final class CoverBoardModel {
    var venues: [CoverVenueCard] = []
    var state: LoadState = .idle

    func loadCached() async
    func refresh() async
    func submit(_ report: PendingCoverSubmission) async
}
```

## 26.4 Native UI

Use native:

- navigation;
- sheets;
- menus;
- haptics;
- location;
- accessibility;
- Dynamic Type;
- reduced-motion support;
- VoiceOver;
- semantic colors;
- SF Symbols where appropriate.

## 26.5 Preserve established UX

The native rewrite SHOULD preserve validated interaction ideas from the current app.

It MUST NOT redesign every flow merely because the technology changes.

---

## 27. Local SQLite database

## 27.1 Role

The local database is:

- a durable cache;
- an offline submission outbox.

It is not a second domain database.

## 27.2 Initial schema

A minimal schema MAY use:

```text
api_cache
  key
  payload_json
  etag
  fetched_at
  server_generated_at
  expires_at

submission_outbox
  id
  submission_kind
  payload_json
  observed_at
  created_at
  attempt_count
  last_attempt_at
  last_error
  state

local_metadata
  key
  value
```

Normalization MAY be added later for high-volume local queries.

## 27.3 Cache behavior

On launch:

1. Read cached cover and deal responses.
2. Render immediately.
3. Show original freshness.
4. Refresh from server.
5. Replace cache transactionally.

## 27.4 Outbox behavior

When offline:

1. Capture observation time.
2. Capture location and displayed-state receipt.
3. Save the full request in SQLite.
4. Acknowledge local receipt.
5. Retry when connectivity returns.
6. Preserve original idempotency key.

## 27.5 Secrets

The following MUST remain in Keychain, not SQLite:

- installation token;
- account session token;
- other authentication secrets.

## 27.6 No local inference

SQLite does not contain a Swift copy of:

- trust resolver;
- cover model;
- nowcast;
- deal predictor.

Offline display is the last server answer, not a newly computed answer.

GRDB is used because it provides explicit SQLite access, schema migrations, transactions, and safe concurrency in a native Swift package.

---

## 28. Android application

Android is deferred until it is a real product milestone.

When built, it uses:

- Kotlin;
- Jetpack Compose;
- native Android architecture;
- a local SQLite/Room cache and outbox;
- generated OpenAPI client;
- RevenueCat;
- Android secure credential storage.

The Android client shares:

- OpenAPI;
- product semantics;
- server behavior;
- fixtures;
- acceptance tests;
- design language.

It does not share UI runtime code with iOS.

---

## 29. Django backend structure

Suggested server layout:

```text
server/
  config/
  identity/
  venues/
  submissions/
  covers/
  vibes/
  deals/
  context/
  handbook/
  billing/
  operations/
```

### 29.1 Cover module

```text
covers/
  models.py
  api.py
  schemas.py
  trust.py
  live.py
  historical.py
  nowcast.py
  resolver.py
  time_machine.py
  decisions.py
  training.py
  evaluation.py
  admin.py
  tests/
```

### 29.2 Deal module

```text
deals/
  models.py
  api.py
  schemas.py
  identity.py
  evidence.py
  resolver.py
  predictor.py
  training.py
  evaluation.py
  admin.py
  tests/
```

### 29.3 No automatic repository layer

Django ORM is the normal data-access layer.

A separate repository class is justified only when it removes real duplication or isolates a difficult external dependency.

A service function is justified when it owns a real use case or transaction.

Pass-through layers are prohibited.

---

## 30. PostgreSQL data model

The following is conceptual, not final SQL.

### 30.1 Identity

```text
installation_actor
installation_credential
account
verified_email
actor_account_link
account_session
```

### 30.2 Venues

```text
venue
venue_alias
```

### 30.3 Submissions and observations

```text
submission
cover_observation
vibe_observation
deal_evidence_event
```

### 30.4 Cover model

```text
cover_model_release
cover_decision
shadow_cover_prediction
cover_training_revision
```

### 30.5 Context

```text
source_fetch
source_health
academic_period
sports_event
weather_record
tradition_event
venue_event
advertised_admission
```

### 30.6 Deals

```text
deal_family
deal_alias
deal_definition
deal_prediction_release
deal_prediction
deal_evidence_event
```

### 30.7 Data imports

```text
dataset_release
dataset_import_run
```

### 30.8 Content

```text
handbook_page
```

### 30.9 Billing

```text
account_entitlement
revenuecat_event
```

### 30.10 Operations

```text
job_run
audit_event
```

---

## 31. Historical data imports

## 31.1 Separation from migrations

Django migrations own:

- tables;
- columns;
- constraints;
- indexes;
- small required reference values.

Historical datasets are imported separately.

## 31.2 Versioned releases

Suggested structure:

```text
data/
  cover/
    recovered-cover-v1.*
    manifest.json

  deals/
    historical-deals-v1.*
    manifest.json

  venues/
    venues-v1.*
    manifest.json
```

The exact file format MAY be JSONL, CSV, or Parquet based on the dataset.

## 31.3 Import commands

```text
python manage.py import_venues ...
python manage.py import_cover_dataset ...
python manage.py import_deal_dataset ...
```

## 31.4 Import receipt

Conceptual fields:

```text
dataset_release
  name
  content_hash
  schema_version
  importer_version
  source_manifest
  created_at

dataset_import_run
  dataset_release_id
  code_revision
  started_at
  completed_at
  rows_seen
  rows_accepted
  rows_rejected
  result
```

## 31.5 Reprocessing

The original source data MUST remain available.

An improved importer can create a new import run or release.

It MUST NOT require rewriting old schema migrations.

---

## 32. Background and scheduled work

## 32.1 Initial model

Background work is executed as Django management commands.

Examples:

```text
python manage.py refresh_context
python manage.py train_cover_model
python manage.py run_cover_challengers
python manage.py refresh_deal_predictions
python manage.py reconcile_revenuecat
python manage.py cleanup
```

## 32.2 Scheduler

A managed scheduler or cron invokes commands.

The same backend image is used.

## 32.3 Coordination

PostgreSQL advisory locks MAY prevent duplicate execution.

A `job_run` row records:

- start;
- completion;
- status;
- error;
- code revision;
- result summary.

## 32.4 No queue initially

Redis and Celery are deferred.

They become justified only if the system develops work that needs:

- many independent tasks;
- immediate asynchronous dispatch;
- priority queues;
- large worker pools;
- task-specific retries;
- long-running concurrency.

A 15-minute nightly training command is not, by itself, a queue problem.

---

## 33. Django Admin

Django Admin is the initial internal operations and CMS surface.

It SHOULD support:

- venue management;
- venue aliases;
- handbook pages;
- report review;
- exact private report evidence for authorized staff;
- deal families and aliases;
- deal correction;
- context-source health;
- dataset import receipts;
- cover-model releases;
- challenger comparisons;
- decision-receipt inspection;
- job runs;
- RevenueCat entitlement inspection.

The public app MUST NOT reuse Admin as a user-facing interface.

Django’s own documentation positions Admin as a trusted internal, model-centric management interface, which matches this use.

---

## 34. IlliniCover Blue and RevenueCat

## 34.1 Entitlement owner

The IlliniCover account owns IlliniCover Blue access.

A device does not own IlliniCover Blue access.

## 34.2 Purchase requirement

A user MUST sign into an IlliniCover account before purchasing IlliniCover Blue.

Guest actors do not buy IlliniCover Blue.

This avoids anonymous purchase-identity merging.

## 34.3 RevenueCat identity

Use the non-guessable IlliniCover account UUID as the RevenueCat App User ID.

Do not use email as the RevenueCat identifier.

RevenueCat documents that one custom App User ID can represent the same customer across devices and platforms and can access purchased entitlements.

## 34.4 Public product and entitlement

The public product name is **IlliniCover Blue**. The stable internal RevenueCat
entitlement identifier remains:

```text
premium
```

The production product identifiers intentionally retain their internal
`premium` namespace while App Store and in-app display names use IlliniCover
Blue. The initial U.S. plan slate is:

| Plan | Internal product identifier | Price | Presentation |
| --- | --- | ---: | --- |
| Annual | `com.illinicover.app.premium.yearly` | $12.99/year | Primary; best subscription value |
| Monthly | `com.illinicover.app.premium.monthly` | $1.99/month | Primary; flexible |
| Weekly | `com.illinicover.app.premium.weekly` | $0.99/week | Expanded choices |
| Six months | `com.illinicover.app.premium.sixmonth` | $7.99/six months | Expanded choices |
| Lifetime | `com.illinicover.app.premium.lifetime` | $24.99 once | Expanded choices; non-consumable |

Store-localized price and renewal terms are authoritative in the app. Annual,
monthly, weekly, and six-month plans renew until canceled; lifetime is a
one-time purchase. IlliniCover Blue currently unlocks extended Time Machine and
history access. No introductory trial or discounted launch price is promised by
this initial slate. The paywall MUST disclose recurring cadence before purchase
and MUST NOT rely on accidental renewal. Future features do not substitute for
present purchase value.

## 34.5 Server authorization

Django receives RevenueCat webhooks and mirrors entitlement state.

IlliniCover Blue API endpoints MUST be authorized server-side.

The client’s RevenueCat state is not sufficient for protected server responses.

## 34.6 Reconciliation

A scheduled command SHOULD reconcile entitlement state with RevenueCat.

---

## 35. Privacy and data retention

## 35.1 Location

IlliniCover MAY capture location only during an intentional user action such as report submission.

IlliniCover MUST NOT continuously track location.

When provided, the system preserves:

- latitude;
- longitude;
- accuracy;
- observation time.

This allows future recalculation of:

- distance thresholds;
- accuracy quality;
- impossible travel;
- venue-proximity logic.

## 35.2 Public location

Exact location MUST never appear in public APIs or public report history.

## 35.3 Network metadata

Server-observed IP and network metadata MAY be used for abuse correlation.

Because network location is noisy, it MUST NOT be treated as strong proof that a person is physically at a venue.

Raw IP retention SHOULD be limited.

Long-lived derived abuse relationships MAY be retained when appropriately deidentified.

## 35.4 Raw evidence access

Exact location, network metadata, and internal trust signals are restricted to:

- backend code;
- authorized administrators;
- debugging and abuse review.

## 35.5 Data disclosure

The privacy policy MUST clearly state:

- which location is collected;
- when it is collected;
- why it is kept;
- how it affects reports;
- how a user can delete data;
- that IlliniCover does not continuously track them.

---

## 36. Security

### 36.1 Credentials

Installation and account tokens MUST be:

- high entropy;
- stored hashed on the server;
- transmitted only over TLS;
- stored in secure client storage.

### 36.2 Email codes

Email codes MUST have:

- short expiry;
- attempt limits;
- resend limits;
- rate limits;
- non-enumerating outward behavior where practical.

django-allauth already supports configurable email login codes, expiry, and resend behavior.

### 36.3 Submission abuse controls

Use layered limits by:

- installation actor;
- account;
- venue;
- network;
- time window.

Rate limits SHOULD store evidence rather than become the trust model itself.

### 36.4 Admin security

Admin access requires:

- staff account;
- MFA;
- least-privilege permissions;
- audit logging.

### 36.5 RevenueCat webhooks

RevenueCat webhook requests MUST be authenticated and idempotent.

### 36.6 Database roles

Production SHOULD separate:

- application role;
- migration role;
- read-only support role.

Clients never receive database credentials.

---

## 37. Observability and support

## 37.1 Logging

The backend SHOULD emit structured logs with:

- request ID;
- actor ID where permitted;
- account ID where permitted;
- endpoint;
- decision ID;
- model release;
- job ID;
- error code.

Sensitive values MUST be redacted.

## 37.2 Error monitoring

Use one error-monitoring service such as Sentry for:

- backend exceptions;
- iOS crashes;
- job failures;
- release correlation.

Broad session replay is not required.

## 37.3 Domain debugging

A user bug report SHOULD include:

- app version;
- operating system;
- venue;
- approximate time;
- decision ID;
- request ID where available.

Admin tooling SHOULD reconstruct:

- model release;
- reports considered;
- excluded evidence;
- nowcast adjustments;
- context;
- resolver version;
- result.

## 37.4 Product analytics

Initial analytics SHOULD be narrow and event-based.

Examples:

- cover board opened;
- report flow opened;
- cover submitted;
- vibe submitted;
- deal confirmed;
- Time Machine opened;
- premium purchase started;
- premium entitlement active.

Do not install broad autocapture by default.

---

## 38. Testing strategy

## 38.1 Principle

Tests protect product behavior and data invariants.

They do not exist to preserve every internal seam.

## 38.2 Cover unit tests

Required cases include:

- one ordinary report becomes live;
- no location remains neutral;
- nearby location strengthens context;
- actor deduplication;
- estimate echo is not independent evidence;
- manual correction is stronger evidence;
- newer coherent reports can replace older reports;
- isolated outlier does not always replace a coherent cluster;
- material conflict can produce a range;
- same-night venue adjustment;
- same-night campus adjustment;
- nowcast decay;
- service-night cutoff;
- retrospective Time Machine;
- historical as-of evaluation;
- model release reproducibility;
- decision receipt reconstruction.

## 38.3 Vibe tests

- one value per dimension per submission;
- vibe-only submission;
- cover-only submission;
- cover-plus-vibe submission;
- no-empty-submission rule;
- independent freshness.

## 38.4 Deal tests

- add missing;
- confirm;
- deny;
- correct;
- canonical alias resolution;
- unresolved custom deal;
- timing distinction;
- unknown timing remains unknown;
- different servings remain distinct;
- evidence lineage;
- predictor evaluation.

## 38.5 Identity tests

- guest installation creation;
- guest reporting;
- email-code account creation;
- actor-account linking;
- multi-device actor links;
- account deletion;
- guest actor rotation;
- session expiry;
- entitlement authorization.

## 38.6 Offline tests

- cached cover renders before refresh;
- cached freshness remains honest;
- offline report enters outbox;
- retry preserves observed time;
- duplicate retry remains idempotent;
- stale delayed report does not become fresh;
- failed submission remains recoverable.

## 38.7 Database tests

- migration from blank;
- constraints;
- idempotency;
- import idempotency;
- model-release immutability;
- decision-receipt references;
- deletion behavior;
- concurrent scheduled-command lock behavior.

## 38.8 Model tests

- chronological folds;
- no future leakage;
- final untouched holdout;
- venue slices;
- time slices;
- context ablations;
- nowcast ablation;
- campus-adjustment ablation;
- shadow challenger comparison;
- calibration and interval behavior.

## 38.9 Client tests

iOS:

- Swift Testing for models and database logic;
- UI tests for critical flows;
- generated-client compilation;
- accessibility tests for core screens.

## 38.10 What not to test

Do not add tests whose main purpose is preserving:

- exact directory layering;
- route metadata;
- cache-key tuple shapes;
- pass-through wrappers;
- exact CI command strings;
- exact documentation prose;
- theoretical platform boundaries.

## 38.11 Coverage

Coverage is reported.

There is no global percentage gate.

Critical domain code MAY have targeted coverage requirements.

---

## 39. CI and pull-request process

## 39.1 Path-sensitive CI

### Server changes

Run:

- dependency lock verification;
- lint;
- unit tests;
- PostgreSQL integration tests;
- migrations;
- OpenAPI generation and diff;
- relevant model tests.

### iOS changes

Run:

- build;
- Swift tests;
- targeted UI tests;
- generated OpenAPI client build.

### Data/model changes

Run:

- import validation;
- dataset hash validation;
- chronological evaluation;
- challenger comparison;
- model receipt generation.

### Documentation-only changes

Do not boot the full application stack.

## 39.2 Full scheduled validation

Nightly or scheduled CI MAY run:

- full model backtest;
- all migration paths;
- full iOS UI suite;
- cold database import;
- context-source contract checks.

## 39.3 Pull-request shape

A PR SHOULD represent one vertical behavior or one clear infrastructure change.

Large transitions SHOULD use:

1. new schema;
2. import/backfill;
3. new code path;
4. cutover;
5. old-code removal.

## 39.4 Generated artifacts

Generated OpenAPI changes SHOULD be isolated and explained.

## 39.5 No architecture bureaucracy

There is no architecture-policy test suite unless a repeated real failure proves one necessary.

---

## 40. Deployment

## 40.1 Production shape

```text
one Django web deployment
one managed PostgreSQL database
one scheduler invoking the same Django image
one transactional email provider
RevenueCat
error monitoring
```

## 40.2 No mandatory Redis

Redis is absent initially.

## 40.3 Database backups

Production PostgreSQL MUST provide:

- automatic backups;
- point-in-time recovery where available;
- tested restore procedure.

## 40.4 Schema deployment

Use expand-and-contract migrations:

1. add compatible schema;
2. deploy code that uses it;
3. backfill if needed;
4. remove obsolete schema in a later release.

## 40.5 Model deployment

Model promotion is independent from application deployment.

The active model behavior can be changed explicitly and recovered to prior
behavior through a newly issued, freshly evaluated release. Retired release
identities remain retired.

## 40.6 Context failure

A failed context source MUST NOT make the entire cover board unavailable.

The resolver uses the last valid context or degrades to a simpler prediction.

## 40.7 Email failure

Email-provider failure affects account login.

It MUST NOT affect guest browsing or guest reporting.

---

## 41. Monorepo structure

```text
IlliniCover/
  ios/
    IlliniCover/
    IlliniCoverTests/
    IlliniCoverUITests/

  android/
    # added when Android work begins

  server/
    config/
    identity/
    venues/
    submissions/
    covers/
    vibes/
    deals/
    context/
    handbook/
    billing/
    operations/
    manage.py
    pyproject.toml
    lockfile

  api/
    openapi.json

  data/
    cover/
    deals/
    venues/
    manifests/

  docs/
    product/
    architecture/
    model/
    runbooks/

  ops/
    container/
    deployment/
    scripts/
```

There is no:

- separate model repository;
- separate data-platform repository;
- separate admin repository;
- separate authentication service;
- shared JavaScript mobile layer.

---

## 42. Clean rebuild and migration

## 42.1 Strategy

v2 is built alongside the current application.

The old code is used as:

- evidence of product behavior;
- a source of edge cases;
- a UX reference;
- a source of historical datasets;
- a source of model evaluation fixtures.

It is not used as architectural scaffolding.

## 42.2 Data available for migration

The main imported data is:

- historical cover dataset;
- historical drink/deal dataset;
- venue dataset;
- canonical deal identity data;
- deterministic context data where useful.

There is little or no live production user data requiring a complex dual-write migration.

## 42.3 Migration stages

### Stage 1: Freeze requirements

- Preserve existing cover and deal UX references.
- Export historical data.
- Record hashes.
- Document existing model behavior.
- Document current report semantics.

### Stage 2: Create v2 monorepo

- Django project.
- PostgreSQL schema.
- OpenAPI generation.
- SwiftUI app shell.
- GRDB cache and outbox.

### Stage 3: Import venue and historical data

- Versioned import commands.
- Import receipts.
- Data-quality reports.
- Reproducible hashes.

### Stage 4: Build cover evidence path

- installation actors;
- submissions;
- cover observations;
- vibe observations;
- trust signals;
- current resolver.

### Stage 5: Build historical predictor

- chronological evaluation;
- continuous time;
- venue pooling;
- model releases;
- decision receipts.

### Stage 6: Build nowcast and Time Machine

- venue same-night adjustment;
- campus adjustment;
- retrospective reconstruction;
- premium authorization.

### Stage 7: Analyze and build deal predictor

- dedicated historical-data analysis;
- deal identity import;
- evidence actions;
- nightly slate;
- deal prediction release.

### Stage 8: Rebuild native iOS UX

- cover board;
- venue detail;
- report sheet;
- deals;
- handbook;
- account;
- premium.

### Stage 9: Parallel validation

- compare old and new cover decisions;
- run v2 challengers;
- inspect historical reconstructions;
- verify deal parity;
- test offline reporting.

### Stage 10: Beta and cutover

- internal TestFlight;
- limited beta;
- production launch;
- retire old backend;
- archive old repository state.

---

## 43. Launch acceptance criteria

IlliniCover v2 is ready for beta when all of the following are true.

### 43.1 Cover

- One ordinary fresh report can create a live state.
- A singleton untouched estimate echo cannot self-confirm the model.
- Conflicting reports produce sensible current behavior.
- The board works with no reports.
- Historical estimates are reproducible.
- Same-night nowcast can affect later predictions.
- Campus-wide adjustment is bounded.
- Time Machine answers past and future queries.
- Every cover answer has a decision ID.
- Model evaluation passes defined chronological gates.

### 43.2 Reporting

- Guest reporting requires no account.
- Cover-only, vibe-only, and combined reports work.
- At least one observation is required.
- Location is optional.
- Offline submissions retry with original observation time.
- Duplicate retries are idempotent.

### 43.3 Accounts

- Any valid email can create an account.
- Login uses one-time code.
- No password is required.
- Installation actor links to account.
- Multiple devices work.
- Account deletion works.
- Guest actor deletion or rotation works.

### 43.4 IlliniCover Blue

- Purchase requires account.
- RevenueCat uses account UUID.
- IlliniCover Blue works across devices.
- Backend enforces Time Machine access.
- Webhook replay is idempotent.
- Entitlement reconciliation works.

### 43.5 Deals

- Historical dataset imports reproducibly.
- Add, confirm, deny, and correct work.
- Distinct deal variants remain distinct.
- Predictor choice has an evaluation receipt.
- Cover and deal logic remain independent.

### 43.6 Client

- Cached data renders instantly.
- Freshness remains honest.
- Outbox survives app restarts.
- Core flows pass accessibility testing.
- OpenAPI client generation is automatic.

### 43.7 Operations

- New database can be created from migrations and imports.
- Scheduled commands are idempotent.
- Failed context source does not take down cover.
- Database restore has been tested.
- Recovery-candidate issuance is tested without rewriting a retired release's
  authority interval; the isolated reissue/evaluate/promote drill remains an
  operations acceptance gate.

---

## 44. Deferred decisions

The following decisions are intentionally deferred.

### 44.1 Exact cover model implementation

The model shape is constrained by this spec.

The exact algorithm and library are selected by evaluation.

### 44.2 Exact deal predictor

Must follow historical deal-data analysis.

### 44.3 Exact live horizon

Initial value may resemble the existing 60-minute rule.

Final value should be evaluated.

### 44.4 Exact Time Machine free limits

Product decision.

### 44.5 Sign in with Apple

Deferred until the value exceeds credential-linking complexity.

### 44.6 Android launch date

Deferred.

### 44.7 Redis or task queue

Deferred until there is queue-shaped work.

### 44.8 Wagtail or advanced CMS

Deferred until Django Admin fails a real editorial workflow.

### 44.9 Automated social/media extraction

Deferred and isolated from the core architecture.

### 44.10 Extra context features

Preserve first. Admit to the predictor only after evaluation.

---

## 45. Explicitly rejected architecture

The v2 implementation MUST NOT recreate the following without a new, documented reason:

- Expo or React Native for the iOS client;
- a platform presenter layer;
- route-presentation contracts;
- a shared cross-platform UI runtime;
- Supabase Edge Functions as the application architecture;
- endpoint-per-function deployment;
- direct client-to-database application access;
- a shared TypeScript runtime mirror;
- account handoff between anonymous Auth users;
- request-time prediction writes as a requirement;
- giant immutable feature-snapshot hierarchies;
- a generic evidence engine;
- a universal `type + value_json` observations table;
- a model microservice;
- a model router in the user path;
- multiple user-visible cover models;
- global coverage vetoes;
- architecture regex tests;
- schema migrations containing large historical datasets;
- automatic context-feature admission;
- permanent user trust scores;
- continuous location tracking.

---

## 46. Final reference stack

```text
PRODUCT

Cover board
Cover reporting
Vibe reporting
Recent reports
Premium Time Machine
Drink deals
Handbook
Account and premium


IOS

Swift
SwiftUI
Observation
Swift concurrency
GRDB / SQLite
Swift OpenAPI Generator
RevenueCat
Keychain
CoreLocation
OSLog


ANDROID, LATER

Kotlin
Jetpack Compose
local SQLite cache/outbox
generated OpenAPI client
RevenueCat


BACKEND

Python
Django
Django Ninja
django-allauth headless
Django ORM
Django migrations
Django Admin
Django management commands


DATABASE

PostgreSQL


MODEL

one authoritative cover model
continuous time
venue partial pooling
same-night venue nowcast
small campus-wide nowcast
shadow challengers
chronological evaluation
versioned model releases
compact decision receipts


AUTH

guest installation actors
optional email-code account
no passwords initially
no Sign in with Apple initially
actor-account linking
no report ownership transfer


BILLING

RevenueCat
IlliniCover account UUID as App User ID
server-mirrored premium entitlement


OPERATIONS

one monorepo
one backend image
one managed PostgreSQL database
ordinary scheduled commands
no Redis initially
no Celery initially
structured logs
error monitoring
path-sensitive CI


DATA PRINCIPLE

Preserve observations.
Preserve provenance.
Preserve raw context.
Version models and interpretation.
Derive current answers.
Cache only when useful.
```

---

## 47. Final architectural statement

> **IlliniCover v2 is a native cover-first application backed by one Python/Django/PostgreSQL monolith. It treats community reports as durable evidence, derives current cover from fresh trusted observations, fills sparse gaps with a reproducible historical model, adapts within a service night through bounded venue and campus nowcasts, and reconstructs past and future cover through IlliniCover Blue's Time Machine. Drink deals remain a separate predictive evidence domain. The mobile clients cache server answers and queue offline reports, while the server remains the sole owner of interpretation.**
