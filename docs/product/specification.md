# IlliniCover product specification

**Status:** Normative pre-alpha contract
**Primary platform:** iOS
**Market:** UIUC and Champaign-Urbana nightlife

This document owns required product behavior. `api/openapi.json` owns the wire
contract, `docs/architecture/decisions.md` owns the few implementation choices left
open here, and tests own executable invariants. A module, database column, receipt,
version, or old test is not a requirement merely because it exists in Git history.

`MUST` is required. `SHOULD` is the default unless direct product evidence supports a
different choice. `MAY` is optional.

## 1. Product

IlliniCover's primary job is to answer:

> What is the best current estimate of cover at each relevant UIUC bar?

The default screen is a fast-scanning cover board. Secondary surfaces are:

- venue detail and recent reports;
- cover and vibe reporting;
- past and future Time Machine queries;
- drink-deal discovery and reporting;
- a handbook managed through Django Admin;
- optional email-code accounts; and
- IlliniCover Blue access through RevenueCat.

Cover and deals share venues, contributors, private submission context, database and
API infrastructure. They do not share interpretation, predictors, evidence actions,
confidence semantics, or expiry rules.

## 2. Product principles

- A report is evidence that someone observed something, not an official truth.
- Raw observation values and their provenance survive reinterpretation.
- The server alone resolves cover, trust, deals, history, and predictions.
- A card shows one main answer, not competing live and predicted headlines.
- Missing optional evidence—account, location, or prior history—is neutral.
- One ordinary report is useful unless affirmative evidence says otherwise.
- Clients cache server answers; they do not reproduce server domain logic.
- Before public launch, server, client, schema and canonical data may change together.
  There are no compatibility aliases, fallback contracts, or historical migration
  promises.

## 3. Shared terms and evidence

### Service night

Nightlife is grouped in `America/Chicago` with a 5:00 AM cutoff. Saturday at 1:30 AM
belongs to Friday's service night. Original timestamps remain intact; the service date
is bookkeeping, not a claim about venue hours.

### Submission

A client contribution contains:

- a client UUID used directly for retry idempotency;
- installation actor and optional authenticated account;
- venue;
- client observation time and server receipt time;
- entry path and vantage point;
- optional location and accuracy;
- displayed product state relevant to interpreting the action; and
- one or more cover, vibe, or deal observations.

An accepted submission is immutable. A correction creates later evidence. Received
time never replaces observed time: a delayed offline report remains historical and
must not appear newly fresh.

Observation values are durable. Credentials, account linkage, exact location and raw
network context are separately erasable. Derived classifications may be recomputed.

### Vibes

The supported dimensions are:

- line length: `short`, `medium`, `long`;
- line speed: `slow`, `normal`, `fast`; and
- crowd level: `quiet`, `busy`, `packed`.

A submission contains at most one value for each dimension and at least one real
cover, vibe or deal observation overall. Cover-only, vibe-only and combined cover/vibe
submissions MUST work. Each vibe dimension has independent freshness.

## 4. Cover

### Board and detail

Every active venue remains visible even when no useful answer exists. A card shows:

- venue name;
- one price or range;
- source and honest freshness;
- compact status; and
- report actions.

Product states are:

- **Live:** admitted current reports determine the answer.
- **Historical:** historical behavior, including same-night adjustment, determines it.
- **Mixed:** multiple current prices remain materially plausible.
- **Unusual:** evidence exists but an affirmative trust concern affects presentation.
- **Unavailable:** no useful answer exists.

Venue detail adds recent cover/vibe observations, current deals, basic venue
information, Time Machine, and reporting. It may expose the historical baseline as
secondary context, never as a competing headline.

### Reporting

The reporting flow supports confirm, correct, direct/manual and quick actions. A user
can enter cover, vibes or both; location is optional. `$0` means free. New submitted
cover prices use $5 increments. “Don't know” creates no cover observation.

The server receives enough displayed context to distinguish:

- an untouched confirmation of its historical suggestion; and
- a user who manually changed a different displayed value.

That context is semantic—source, price/range, prefilled and touched state—not a
decision ID or receipt identity.

Successful UI feedback says the report was received or queued. It MUST NOT imply that
one contributor directly changed official cover.

### Admission and resolution

The resolver evaluates observations in context rather than assigning permanent user
scores. It may use recency, timestamp quality, optional location, displayed-state
echo, actor independence, coherent history and affirmative abuse signals.

Required behavior:

- one ordinary fresh manual report can establish live cover;
- no account, location or actor history is neutral;
- one untouched echo of the historical suggestion is not independent training
  evidence and does not alone relabel the card live;
- independent corroboration may establish that echoed value;
- newer coherent evidence may replace an older cluster;
- an isolated outlier need not replace a coherent cluster;
- material current conflict may produce a range;
- exact abuse reasons never appear publicly; and
- invalid or abusive input may be rejected while unusual evidence may be retained but
  excluded from public state.

The answer is computed from evidence; the database does not store a mutable
`venue.current_cover` truth. Responses include source, freshness, computation time,
target time and knowledge cutoff. They do not create persisted decision receipts.

### Historical prediction and nowcast

The historical estimate uses admitted observations from completed service nights. It
models clock time in order, retains venue-specific behavior, and may borrow weakly
from campus-wide behavior where a venue is sparse. It does not train on reconstructed
Time Machine paths as if they were observations.

Same-night observations may adjust later historical estimates for that venue. A
smaller bounded campus adjustment may help venues with no own live evidence. Current
live evidence remains dominant. Evaluation is chronological and MUST prevent future
leakage.

The deployed application revision contains the one production cover model. Candidate
algorithms are compared offline. There is no runtime model-release registry,
promotion journal, shadow scheduler or independent model rollback path.

### Advertised admission

A current, qualified and unconditional advertised admission fact may directly inform
the answer. Conditions such as age, gender, ticket, wristband or “before 9” remain
attached and MUST NOT become a universal cover price.

### Recent history and Time Machine

Public report history may show price, age, safe source context and vibes. It MUST NOT
show exact coordinates, contributor/account/device identifiers, network metadata or
internal suspicion reasons.

Initial history policy:

- Free: seven service nights, at most 50 admitted reports per venue.
- Blue: 90 service nights, at most 250 admitted reports per venue.

The response states the applied tier/window. Premium changes depth, never which
private fields are exposed.

Time Machine answers IlliniCover's best present reconstruction or prediction, not an
official archived fact. It supports ten years into the past and one year into the
future. Targets within 60 seconds of the server cutoff are `current`; the server owns
the returned `past`, `current` or `future` mode.

- Past may use later evidence from the same service night for retrospective
  reconstruction.
- Future uses only information known at the current cutoff.
- Historical evaluation uses the cutoff that would have existed at prediction time.

Free users may inspect current/recent history. Arbitrary supported past queries,
future queries and extended history require Blue.

## 5. Deals

Deals are resolved independently from cover. The nightly slate keeps every active
venue visible and may answer a target time.

A concrete offer preserves distinctions in:

- canonical family and display name;
- category;
- absolute, ranged or relative price;
- unit and serving format;
- timing; and
- while-supplies-last status.

Different price, serving or timing means a different offer. Unknown timing remains
unknown and MUST NOT silently become “all night.”

Evidence actions are add missing, confirm present, deny present and correct. Denial
does not delete history; correction adds later evidence. Confirm, deny and correct
target the public deal ID. Add missing has no target.

User-authored custom text remains private evidence until the server resolves it to a
reviewed public identity. Approximate text similarity MUST NOT silently publish a new
deal. Public corrections may reuse a trusted target's label while changing constrained
numeric, enum and boolean fields.

The deployed application derives weekday recurrence directly from canonical
historical facts and overlays corroborated current evidence at request time. It does
not materialize a second daily prediction table or operate a deal-release control
plane. Model comparison remains chronological and separate from cover evaluation.

## 6. Identity, accounts and billing

### Installation actors

Browsing and reporting do not require an account. Reporting uses a pseudonymous
installation token stored in Keychain and hashed on the server.

Credential issuance has no recovery receipt. A lost creation response may leave an
empty orphan actor; a later creation succeeds normally and bounded cleanup may remove
unused actors. Rotation deidentifies/deletes private context for the old actor and
returns a new actor. A lost rotation response may likewise create a fresh actor.

Submission UUIDs and database uniqueness own offline retry idempotency. Installation
creation, rotation and account linking do not add generic request IDs or payload
fingerprints around their existing database/authentication guarantees.

### Accounts

Accounts are optional and use django-allauth headless email codes with no password.
Email is a credential, not the stable account identity. Linking an installation never
rewrites its observations. Multiple installations may link to one account.

Account deletion is synchronous. It removes credentials, sessions, links,
entitlement state and private account context. A client retry that is unauthorized
after a lost deletion response treats the deletion as complete and purges local
account state.

Guest rotation and account deletion MUST leave no stable deleted-person pseudonym,
exact location, raw network identity, email or provider account identifier in retained
observations.

### IlliniCover Blue

A signed-in IlliniCover account owns Blue access. Purchase requires an account;
RevenueCat uses the non-guessable account UUID, never email, as App User ID. The server
authorizes premium API responses; client RevenueCat state alone is insufficient.

The public name is **IlliniCover Blue** and the RevenueCat entitlement identifier is
`premium`. Initial products are:

| Plan | Product identifier | Initial US price |
| --- | --- | ---: |
| Annual | `com.illinicover.app.premium.yearly` | $12.99/year |
| Monthly | `com.illinicover.app.premium.monthly` | $1.99/month |
| Weekly | `com.illinicover.app.premium.weekly` | $0.99/week |
| Six months | `com.illinicover.app.premium.sixmonth` | $7.99/six months |
| Lifetime | `com.illinicover.app.premium.lifetime` | $24.99 once |

Store-localized price and renewal terms are authoritative. The paywall discloses
recurring cadence. Webhooks are authenticated and idempotent by provider event ID.
One account-locked entitlement projection owns authorization, and reconciliation
repairs missed or ambiguous provider events.

## 7. iOS application

The application is native Swift/SwiftUI using Observation, structured concurrency,
URLSession, Codable, GRDB, RevenueCat, CoreLocation, Keychain and OSLog.

There is one direct API client and one wire/cache representation. The app MUST NOT
contain a generated client tree, parallel domain mirror, fake product backend,
repository protocol per endpoint, route metadata, presenter layer, TCA/Redux, generic
dependency injection, shared JavaScript runtime or local copy of server inference.

### Cache and outbox

SQLite is a durable response cache and submission outbox, not a second domain store.
On launch the app:

1. renders cached cover/deal answers with their original freshness;
2. refreshes from the server; and
3. replaces cached responses transactionally.

When offline it stores the full submission, original observed time and same client
UUID, acknowledges the local queue, and retries later. Permanent failures remain
visible/recoverable rather than disappearing. Installation and account secrets remain
in Keychain.

The pre-alpha local database has one current schema. Obsolete caches may be recreated;
there is no compatibility migration chain. Resetting cache MUST NOT silently discard
a readable current-schema outbox or Keychain credentials.

### Native interaction and accessibility

Use native navigation, sheets, menus, alerts, ShareLink, controls, haptics, focus,
Dynamic Type, VoiceOver, semantic colors and reduced-motion behavior. Preserve the
useful report/deal interaction semantics, not old internal routing or pixel machinery.

Core screens MUST remain usable in light/dark appearance, large Dynamic Type, VoiceOver
and poor connectivity. Location is requested only during an intentional report action.

## 8. Server, API and data

The backend is one Django application, one deployable image and one PostgreSQL
database. Django Ninja owns typed API schemas; Django ORM and database constraints are
the normal persistence boundary. Cover and deal interpretation remain separate
functions, not separate services or generalized engines.

The sole pre-alpha API lives at `/api/`. There is no `/api/v2` alias or compatibility
negotiation. Authentication endpoints are provided by allauth. OpenAPI is generated
to `api/openapi.json`; the iOS Codable client is proven against the real Django API.

Error responses use one safe shape with code, human message and request ID. Read
responses carry honest generation/freshness fields and ordinary cache-control; custom
ETag/hash machinery is not required.

Canonical bootstrap inputs are:

- `data/venues.jsonl`;
- `data/covers.jsonl`; and
- `data/deals.jsonl`.

Rows retain only product/model fields and useful source pointers. Git owns history;
there are no dataset manifests, release versions, import hashes or import-receipt
tables. `manage.py bootstrap` atomically loads a fresh database and reports counts.

Background work is limited to real work such as RevenueCat reconciliation and bounded
cleanup. The scheduler owns invocation history; provider logs and process status own
execution receipts. No Redis, Celery or application job ledger is required.

`/health/live` proves the process is alive. `/health/ready` proves database/schema and
core serving readiness. Optional email, RevenueCat or future providers expose
capability state and MUST NOT make guest browsing/reporting unready.

## 9. Privacy and security

- Location is collected only during an intentional report and never continuously.
- Exact location, actor/account/device identifiers, credentials, IP/network metadata
  and trust reasons never enter public APIs.
- Raw private evidence is accessible only to backend code and authorized staff.
- Installation/account tokens are high entropy, TLS-only, hashed server-side and held
  in secure client storage.
- Email codes have short expiry, attempt/resend limits, rate limits and outwardly
  non-enumerating behavior where practical.
- Submission abuse controls may consider actor, account, venue, network and time, but
  rate limits do not become permanent trust scores.
- RevenueCat webhook authentication and replay protection are trust boundaries and
  MUST NOT be simplified away.
- Admin requires staff authentication, MFA, least privilege and Django's audit log.
- Production separates application and migration database authority. Clients never
  receive database credentials.
- Logs and Sentry use a small explicit safe allowlist. Rich payloads are omitted rather
  than recursively redacted after collection.

The published privacy policy states what is collected, when, why, retention, deletion,
and the absence of continuous tracking.

## 10. Verification and release

Tests protect behavior and trust-boundary invariants, not internal seams. Do not test
directory layout, pass-through wrappers, exact workflow text, cache-key tuples,
documentation prose, compatibility paths that do not exist, or changing code/count
statistics.

The compact automated suite MUST cover:

- one-report live behavior, echo protection, conflict/range, outliers, service-night
  cutoff, no-future-leakage, historical/nowcast and Time Machine modes;
- cover-only, vibe-only, combined, offline retry and UUID idempotency;
- deal recurrence, distinct shapes, unknown timing and add/confirm/deny/correct;
- guest issuance/rotation, account link/deletion and private-data erasure;
- webhook authentication/replay, entitlement authorization and reconciliation;
- PostgreSQL uniqueness/concurrency/privacy constraints;
- blank migration plus canonical bootstrap; and
- OpenAPI diff plus real iOS/Django contract integration.

There is no global coverage percentage, architecture-policy suite, source-regex suite,
hash ledger or mutable numerical interpretation gate.

### Deployment

Production uses one Cloud Run service, one migration/preparation job, managed
PostgreSQL, transactional email, RevenueCat and error monitoring.

For each revision:

1. build one image identified by provider digest and Git commit;
2. migrate and bootstrap canonical data before traffic;
3. deploy a no-traffic candidate revision, or a private initial revision when the
   service does not yet exist;
4. read back image, code revision, database mode and secret reference;
5. probe live, ready, status and useful cover/deal payloads on the candidate;
6. promote the candidate to 100% traffic or make the probed initial service public;
7. probe the stable origin and remove the temporary candidate tag; and
8. on any failure after a candidate attempt, restore the previous revision and
   remove the candidate, or delete the failed service when no previous revision exists.

The provider owns immutable image/revision identity and cleanup. The repository does
not duplicate it into release receipts or reconstruct provider state. Production
PostgreSQL provides backups and point-in-time recovery, with a tested restore path.

Before public launch the database may be recreated from the current initial migration
and canonical data. Once real user data must survive releases, expand-and-contract
migrations become mandatory.

### Runtime acceptance

A build alone is not runtime proof. A release candidate is installed and launched
against a real Django/PostgreSQL backend. Retained provider artifacts include settled
light/dark screenshots, accessibility trees, bounded app/server logs, `.xcresult`,
environment identity and an explicit scenario manifest. Fake clients, bundled fixture
JSON and old screenshots cannot satisfy acceptance.

## 11. Explicit non-goals

Until a shipped requirement proves otherwise, IlliniCover has no:

- Android client;
- React Native, Expo or shared UI runtime;
- microservices or endpoint-per-function deployment;
- direct client/database access;
- Redis, Celery, queues, WebSockets or general sync engine;
- model service, runtime model router or promotion platform;
- generic evidence/event-sourcing/EAV framework;
- speculative context adapters, social scraping or automated OCR;
- advanced CMS beyond Django Admin;
- permanent user reputation score;
- continuous location tracking;
- request-time prediction writes or materialized daily deal slate;
- persisted decision receipts, release hashes or compatibility versions; or
- architecture/source-shape verification bureaucracy.

## 12. Beta acceptance

IlliniCover is beta-ready when:

- the board works with live, historical, mixed and unavailable venues;
- one ordinary report can become live while a singleton model echo cannot;
- cached answers and offline outbox remain honest across relaunch;
- Time Machine past/future behavior and Blue authorization work;
- deal discovery and all four evidence actions preserve distinct shapes;
- guest, account, multi-device, deletion and rotation flows work;
- RevenueCat normal, replay, outage and reconciliation paths work;
- canonical data creates a useful slate from a blank database;
- privacy scans find no deleted credential, linkage, exact location, network or
  provider identity;
- accessibility and real-backend runtime scenarios pass; and
- candidate deployment, stable readback and traffic rollback have been exercised.
