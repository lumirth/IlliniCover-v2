# Context source boundary

There is no static v1 context dataset in this release. Academic dates, sports,
traditions, and weather are moving external inputs and must be ingested by the
v2 server with their own source timestamps, freshness state, and provenance.
Copying a database snapshot would turn stale derived state into apparent
evidence.

Reviewed venue-published admission facts have an explicit operational ingest:
`python server/manage.py import_advertised_admissions INPUT --source-identifier
... --source-url https://... --fetched-at ... --external-key ...`. The JSON
contains typed `venueSlug`, `priceCents`, `startsAt`, optional `endsAt`,
`qualification`, and `isUnconditional` fields. The importer hashes the exact
document, stores source URL/fetch/parser provenance, is idempotent, and rejects
qualified facts mislabeled as unconditional. It deliberately does not scrape or
infer a venue price.

The reviewed source families are:

- UIUC Academic Dates ICS for instruction, break, reading-day, finals,
  commencement, summer, and winter periods;
- ESPN Illinois football schedules, with regular- and postseason schedule
  types tracked separately;
- the Fighting Illini composite ICS for Homecoming and family-weekend signals;
- deterministic, versioned local rules for Halloween, Unofficial, and
  Thanksgiving Eve windows; and
- Open-Meteo hourly forecast weather.

The v2 ingest must review each provider's current terms and retention rules,
record the exact fetched URL and observation time, and preserve unknown when a
source is missing or stale. Open-Meteo attribution is required anywhere its
weather-derived features are described externally. This inventory is
provenance guidance, not a license grant and not an imported data release.
