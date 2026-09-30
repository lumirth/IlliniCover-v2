# Bootstrap inputs

- `venues.jsonl` contains the four product venues.
- `covers.jsonl` contains private normalized historical cover observations.
- `deals.jsonl` contains private normalized historical deal facts.

`python server/manage.py bootstrap` loads these files into a fresh database.
Only the venue catalog is distributed with the source. Historical inputs and
their original provenance are retained locally or in authorized private storage,
not Git. A fresh checkout needs these two inputs supplied privately before
bootstrap, corpus evaluation or a deployment build. Do not substitute invented
observations or publish the datasets to make those commands pass.

Rows retain the source identifiers and product values needed to understand their
provenance in private storage. They are internal evidence, not a declaration that third-party source
material is licensed for redistribution. Do not expose source handles, post keys,
Firestore keys, or private provenance through public APIs or telemetry.
