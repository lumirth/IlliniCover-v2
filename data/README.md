# Versioned data releases

This directory contains immutable source artifacts and deterministic derived
release products. Historical datasets are imported separately from database
migrations, as required by the product specification.

Release layout:

- `cover/recovered-cover-v1/` preserves the Firestore export and contains a
  normalized, import-oriented JSONL release.
- `deals/historical-deals-v1/` preserves the deterministic historical
  Instagram extraction and its model-selection analysis receipt.
- `deals/deal-identities-v1/` preserves the reviewed canonical identity
  registry used by that analysis.
- `venues/venues-v1/` is the standalone canonical venue and alias release.
- `context/` explains why no moving external context snapshot is imported.

Every release has a manifest with byte counts, SHA-256 hashes, provenance, and
use restrictions. The raw source files are deliberately kept alongside their
derived products so a later importer can reprocess them without rewriting a
schema migration.

## Rebuild

Run from the repository root:

```bash
python3 scripts/data/build_cover_release.py
python3 scripts/data/analyze_deal_recurrence.py
python3 -m unittest discover -s tests/data -p 'test_*.py'
```

The builders use only the Python standard library. Re-running them with the
checked-in source artifacts must reproduce the checked-in derived bytes.

## Handling boundary

These artifacts are an authorized internal migration/evaluation package, not
a declaration that third-party source material is licensed for public
redistribution. Source post identifiers, handles, extracted names, and
Firestore document keys are provenance identifiers and may be pseudonymous.
Keep raw releases server-side and out of public APIs, telemetry, and client
bundles. Publish only the minimum factual fields needed by the product after a
separate rights and privacy review.
