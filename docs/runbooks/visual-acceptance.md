# Local visual-acceptance server

This lane supplies deterministic simulator states through the normal generated
client and HTTP API. It is not a Preview API, a production fixture route, or a
shared database.

The settings module fails closed unless all of these are true:

- `VISUAL_ACCEPTANCE_ENABLED=1` is explicit;
- neither production database URL is present;
- the database is a direct `.sqlite3` child of `.local/visual-acceptance/`;
- no Cloud Run service, revision, job, or execution marker is present;
- the server binds to loopback and the iOS `-liveAcceptance` mode accepts only a
  loopback API origin.

## Create one profile

Use a new database filename for every profile or repeat. The seeder refuses a
database that already contains venues or submissions.

```bash
export VISUAL_ACCEPTANCE_ENABLED=1
export VISUAL_ACCEPTANCE_DB="$PWD/.local/visual-acceptance/cover-states.sqlite3"
export FIXTURE_AT="$(uv run python -c 'from datetime import datetime; print(datetime.now().astimezone().isoformat())')"
export CODE_REVISION="$(python3 scripts/release/source_revision.py)"

case "$CODE_REVISION" in
  src-????????????????????????????????????????????????????????????????) ;;
  *) echo "Invalid visual-acceptance source revision" >&2; exit 64 ;;
esac

uv run python server/manage.py migrate \
  --settings=config.settings.visual_acceptance --noinput
uv run python server/manage.py seed_visual_acceptance \
  --settings=config.settings.visual_acceptance \
  --profile cover-states \
  --at "$FIXTURE_AT"
uv run python server/manage.py runserver \
  --settings=config.settings.visual_acceptance 127.0.0.1:8000
```

Compute `CODE_REVISION` immediately before starting the server, after backend
and fixture source has stopped changing. The visual settings reject
`development` and any value that is not `src-` plus a SHA-256 digest. Before an
accepted capture, read `serverRevision` from `/api/v2/cover` and require it to
equal the exported value. A source edit after server start invalidates that
server and every subsequent capture; recompute and restart instead of reusing
the old process.

Available profiles are:

- `empty`: active venues with unavailable cover and no deals;
- `cover-states`: live, mixed/range, cautious/unconfirmed, advertised single,
  advertised-conflict range, unavailable, overflow, cover-plus-vibe and
  vibe-only timelines, populated and empty deal venues, and rich deal-search
  variants. The leading venue/deal names and prices mirror the clean v1
  comparison state before the v2-only state matrix continues below them;
- `historical`: authoritative KAMS/Joe's/Red Lion `$10` and Brothers `$5`
  estimates matching the clean v1 board, plus a raw off-step `$12` overflow
  fixture proving display provenance and nearest-$5 report normalization remain
  separate;
- `deals-search`: deal card and local/global search variants without live cover
  observations.

Launch a Debug app with `-liveAcceptance` and a loopback API origin. That mode
still instantiates `LiveAPIClient`; `-uiTesting` remains the isolated
`PreviewAPIClient` lane and is not accepted as wire/runtime proof.

## Time and transport states

Normal interaction runs leave `VISUAL_ACCEPTANCE_NOW` unset and seed with the
current aware time, so accepted writes and subsequent reads share the real
server clock. `VISUAL_ACCEPTANCE_NOW` is reserved for deterministic read-only
captures. When set, middleware rejects every mutating request with 409 rather
than allowing fixture time and write time to diverge. An older fixed instant
can therefore create an honest stale read/cache fixture without changing the
simulator clock, but cannot be used for submission-flow evidence.

For a bounded slow or HTTP-failure state, restart only this local server with:

```bash
export VISUAL_ACCEPTANCE_FAULT='GET:/api/v2/deals:pass:2500'
# or: GET:/api/v2/deals:503
# or: POST:/api/v2/deal-evidence:422
```

The grammar is `METHOD:/api/v2/path-prefix:STATUS_OR_PASS[:DELAY_MS]`.
Only `GET` and `POST`, API-v2 paths, error statuses, and delays up to five
seconds are accepted. `pass` delays and then serves the normal response.

Stop the loopback server after a successful fetch to prove a genuine transport
failure, cached-first rendering, and offline outbox behavior. Restart the same
profile to prove recovery and preserved request identity. Use the injected 422
only for the separate permanent-failure UI state.

## Required receipts

Every accepted matrix row records the fixture profile, fixed instant, fault
mode, exact backend `CODE_REVISION` read back as `serverRevision`, API contract
hash, app revision, simulator UDID/runtime, screenshot, accessibility
hierarchy, bounded app/server logs, and exact interaction state. A normal
fixture row must use `LiveAPIClient`; transport and system rows must name the
injected condition.
