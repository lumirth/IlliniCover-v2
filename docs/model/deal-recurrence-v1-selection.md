# Deal recurrence v1 model-selection receipt

Status: selected for the initial v2 deal baseline, with low confidence and
prospective evaluation required.

Production status: superseded by `deal_recurrence_v2` on 2026-08-13 because
the checked launch corpus is frozen at 2026-04-07. Once the production service
date moved beyond 90 days from that corpus, the global freshness cutoff made
all four venue slates empty. The historical v1 receipt remains immutable.

Machine-readable authority:
[`data/deals/historical-deals-v1/model-selection-receipt.json`](../../data/deals/historical-deals-v1/model-selection-receipt.json).

## Decision

Select `deal_recurrence_v1`: for a venue and target service date, inspect the
three most recent earlier source-observed nights with the same weekday. Admit
an offer identity only when it appeared on at least two of those nights. If the
most recent comparable night is more than 90 days old, emit an empty baseline.
For an admitted identity, choose its concrete price/timing/serving variant by
distinct-night frequency, then most recent occurrence, then stable identifier.

Unknown timing remains unknown. The predictor can return an empty venue slate.
Same-night `ADD_MISSING`, `CONFIRM_PRESENT`, `DENY_PRESENT`, and `CORRECT`
evidence is a deterministic overlay with lineage; it does not rewrite imported
history.

The materialized slate also persists a positive, one-based predictor rank for
each venue and service date. Rank follows the selected recurrence evidence:
more supporting comparable nights first, then the most recent supporting
night, then the deterministic deal-definition identifier. This rank orders
predictions that have no same-night evidence; it is not evidence and it is not
inferred by a client.

The public venue slate preserves the v1 display intent. Rows with admitted
same-night evidence come first, newest evidence first. Rows without such
evidence follow predictor rank, then case-folded display name and stable row
identifier. A correction keeps the target prediction's rank while the target
remains visible and passes that rank to an admitted replacement. Prediction or
definition creation timestamps may be shown as activity metadata, but never
count as same-night evidence for ordering.

## Data admitted to analysis

The clean-room normalizer reads only the pinned raw releases:

- historical plan: 6,225 source rows, SHA-256
  `17933f02b1f4ece6b8f15428a0889eb8433d9384c0aa5d0e37b30490151c9691`;
- canonical registry: 3,725 clusters, SHA-256
  `7a1deac2f11bae5cb74f5145cd3d50d60c9b8e31d673d86253bb3c7b31376527`.

It admits 13,786 drink facts and rejects 72 non-unique or unresolved identity
facts. It uses exact reviewed registry membership and aliases; it performs no
fuzzy matching. Collision-safe source-cluster identifiers keep 821 used drink
families distinct, including approved names that normalize to the same slug.

The admitted facts span 2013-12-02 through 2026-04-07 across 4,863
venue/service-date observations. They contain 6,687 unknown-timing rows. The
source has no structured confirmations, denials, or corrections.

## Chronological backtest

The holdout begins 2024-01-01 and contains 1,483 source-observed venue nights.
Every prediction uses strictly earlier dates for that venue. The target is the
set union of exact concrete drink offers extracted for the target
venue/service-date. Metrics are micro-averaged over concrete-deal membership.

| Candidate | Precision | Recall | F1 | Empty slate rate |
| --- | ---: | ---: | ---: | ---: |
| Last same weekday | 0.461488 | 0.460486 | 0.460987 | 0.000000 |
| 2 of last 4 | 0.519040 | 0.464611 | 0.490320 | 0.058665 |
| 2 of last 3 | 0.584911 | 0.422492 | 0.490609 | 0.123399 |
| **2 of last 3, 90-day cap** | **0.593016** | **0.416630** | **0.489416** | **0.146999** |
| 2 of last 3, same phase, 90-day cap | 0.600211 | 0.369952 | 0.457757 | 0.242751 |
| 3 of last 4 | 0.650417 | 0.338906 | 0.445618 | 0.292650 |

The fixed selection rule is: require recall of at least 0.40, then maximize
precision, preferring bounded stale history and an empty result over reviving
an old offer. The selected candidate has the best precision among candidates
that pass the recall gate. The same-phase and 3-of-4 candidates are more
precise but fail that gate. The 90-day cap trades 0.001193 F1 against the
unbounded 2-of-3 model for higher precision and explicit staleness control.

## Production correction: deal_recurrence_v2

The v2 release selects the already-evaluated unbounded `2 of last 3`
candidate. It keeps the same venue, weekday, offer-identity, support, variant,
rank, and same-night evidence-overlay rules, but removes the global age kill
switch. This is a clean immutable release rather than a mutation of v1. Its
machine receipt is
[`model-production-receipt-v2.json`](../../data/deals/historical-deals-v1/model-production-receipt-v2.json).

This does not claim an old offer is currently verified. Predictions retain
their immutable source dates and low-confidence status; current reports remain
free and can confirm, correct, or deny them. The correction prevents a frozen
bootstrap corpus from silently disabling the entire feature while prospective
evidence accumulates.

## Required cautions

These labels are extracted advertisements, not verified point-of-sale truth.
Nights with no source post are absent rather than known-empty, and omission
within a post is not proof an offer was unavailable. A simple date phase is
only a seasonality diagnostic, not authoritative UIUC-calendar context. The
historical source cannot estimate confirmation or denial effects.

Accordingly, this is an initial low-confidence release. Production must record
decision receipts, evaluate prospective confirmation/denial outcomes, preserve
distinct deal variants and unknown timing, and permit rollback. Reproduction
is local and deterministic; it uses no external service, cloud workload, or
paid resource.

## Reproduce

```bash
python3 scripts/data/analyze_deal_recurrence.py
python3 -m unittest discover -s tests/data -p 'test_*.py'
```
