# Database restore and historical model-promotion receipt

Date: August 12, 2026
Project: Neon `orange-bread-24894334`
Production branch: `br-square-star-ay9wrqod`

No credentials, connection strings, raw source records, or private submissions
are included in this receipt.

Status: the point-in-time restore receipt remains current evidence. The model
promotion portion is historical-only and is not acceptance evidence for the
current append-only model-recovery path.

## Point-in-time restore

A temporary child branch named `restore-drill-20260812` was created from the
production branch at `2026-08-12T10:20:00-05:00`, inside the live free-plan
six-hour history window. Neon reported the fork completed in 0.21 seconds. The
temporary branch ID was `br-dry-wildflower-ayxmmw11` and it was configured for
one-day automatic expiry as a second safety boundary.

Direct TLS readback on the restored branch returned:

| Receipt | Restored value |
| --- | ---: |
| venues | 4 |
| cover observations | 1,199 |
| historical deal facts | 13,786 |
| authoritative cover releases | 1 |
| authoritative deal releases | 1 |
| dataset releases | 3 |
| successful import receipts at restore point | 6 |
| Django Site domain | `illinicover-api-1068900473446.us-east5.run.app` |
| `covers.0007` applied | 1 |
| `identity.0003` applied | 1 |

This proves a historical database state, schema history, imports, and model
authority can be materialized independently of the production branch. It does
not claim more history than Neon's current free-plan six-hour window.

## Historical model-promotion drill

On that isolated restored branch only, an immutable drill challenger was made
from the authoritative artifact and a chronological-win-shaped drill receipt.
The existing promotion command:

1. promoted drill candidate `121f2e29-9037-4fb1-b056-5e4dbc544d5b`;
2. read back that candidate as the sole authoritative release;
3. promoted original release `00e28097-8d83-42e2-8291-601ec1ff9293` again;
4. read back the original as authoritative and the candidate as retired; and
5. persisted two successful `promote_cover_model` job receipts.

This was a truthful receipt for the command behavior at the time of the drill,
and it did not mutate production model authority. It is no longer evidence for
the current model-recovery path: current source preserves authority intervals
by rejecting step 3 when the original release has a non-null `retired_at`.

The first promotion still evidences artifact validation, job locking, authority
uniqueness, and audit persistence on the isolated branch. Current source now
implements `issue_cover_model_recovery`, which issues a fresh non-authoritative
candidate identity from the desired retired artifact and binds the current
incumbent as its baseline. Unit and PostgreSQL tests cover registration and the
later evaluation cutoff. A current rollback acceptance receipt must still
evaluate that candidate against the still-current incumbent with a fresh
immutable chronological receipt, promote the new identity, and read back the
preserved retirement timestamps on both historical releases. That complete
reissue/evaluate/promote sequence has not yet been drilled, so this document
must not be cited as proof that current model rollback is complete.

## Cleanup and cost boundary

After validation, the exact temporary branch was manually deleted. Neon then
showed one of ten branches remaining: production only. Project usage at cleanup
readback was 0.21 CU-hours, 0.05 GB storage, 0.01 GB history, and 0.01 GB network
transfer, within the displayed free-plan allowances.
