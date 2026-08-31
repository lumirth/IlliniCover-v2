# Canonical bootstrap data

- `venues.jsonl` contains the four product venues.
- `covers.jsonl` contains normalized historical cover observations.
- `deals.jsonl` contains normalized historical deal facts.

`python server/manage.py bootstrap` loads these files into a fresh database.
Git owns their history; there are no release manifests, schema wrappers, hashes,
or import-receipt tables.

Rows retain the source identifiers and product values needed to understand their
provenance. They are internal evidence, not a declaration that third-party source
material is licensed for redistribution. Do not expose source handles, post keys,
Firestore keys, or private provenance through public APIs or telemetry.
