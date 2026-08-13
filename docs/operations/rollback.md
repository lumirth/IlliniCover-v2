# Production application rollback

Use application rollback for a bad web revision. Do not reverse an additive
database migration and do not use a database restore for an ordinary app bug.

The production workflow records the sole revision receiving 100 percent of
traffic, tags its image `production-rollback`, deploys the new image with no
traffic, and probes its process and database readiness. If failure occurs after
traffic switches, the exit trap restores exactly that recorded revision and
verifies the serving revision readback. Scheduler remains paused on any failed
release.

For a later manual recovery, identify the known-good revision from the failed
workflow receipt or Cloud Run audit history, then run:

```bash
gcloud run services update-traffic illinicover-api \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --to-revisions "${KNOWN_GOOD_REVISION}=100"
```

Read back `status.traffic`, verify exactly one revision receives 100 percent,
then check `/health/live`, `/health/ready`, and `/api/v2/status`. Leave a
compatible migrated schema in place. Use the separate Neon restore drill only
for actual data damage or an approved incompatible destructive migration.

First read back the known-good revision's numeric Secret Manager references.
If every referenced version still exists, the traffic-only command above is
valid. If a version was retired after a credential rotation, do not recreate
the obsolete credential and do not route traffic to the broken revision.
Instead, add one fresh version of the current accepted bundle, deploy the
`production-rollback` image as a new no-traffic revision pinned to that numeric
version, run the normal readiness probes, and then promote it. Destroy the
superseded candidate after the rollback revision is accepted. This is the
explicit secret-aware rollback path; disabled versions are not kept as a
standing rollback archive.
