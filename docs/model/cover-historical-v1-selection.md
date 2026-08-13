# Cover historical v1 model-selection receipt

## Decision

The initial beta fallback is `cover_historical_v1`: a deterministic
continuous-service-time kernel over weekday and clock time with venue partial
pooling toward a campus distribution.

It is intentionally small. It has no manual venue archetypes, context-feature
direction, pairwise venue graph, reconstructed training labels, online
retraining, or client implementation. The server is the only interpreter.

The selected configuration is:

| Parameter | Value |
|---|---:|
| Time kernel bandwidth | 60 minutes |
| Non-matching weekday weight | 0.08 |
| Venue pooling strength | 8 effective observations |
| Likely interval | 15th to 85th percentile |
| High-cover calibration threshold | $20 |

The model returns a discrete weighted median for the main prediction, a
weighted likely interval, zero/high-cover probabilities, effective support,
and the model release. Time remains continuous; the labels used below for time
slices are evaluation reports, not predictor inputs.

## Evidence and admission boundary

The evaluation consumes exactly
`data/cover/recovered-cover-v1/cover-observations-v1.jsonl`, SHA-256
`aaab73ccf1a825e1192f04ff00a0affcf0fb877da3d744ed3a6c33d60ed8674e`:
1,199 normalized observations, four venues, and 518 service dates.

This recovered release does not carry actor, interaction, location, model-echo,
or trust provenance. For this initial historical evaluation only, each
normalized row is treated as one unit-weight legacy observation. This supports
model comparison; it does not validate the live trust policy. New production
training must consume admitted observations from completed service nights and
retain their admission/evidence revision.

## Chronological protocol

No random split is used. Prediction eligibility checks `available_at` and
excludes the service night active at the explicit knowledge cutoff.

- Older rows remain available as rolling training history.
- Candidate selection scores 593 observations from 2023-09-04 through the day
  before 2025-05-18, with each service date acting as a rolling-origin fold.
- The newest 260 observations from 2025-05-18 through 2025-11-18 form the final
  holdout.
- Selection uses MAE, then interval score, zero-cover Brier, and stable release
  ID as tie-breakers.
- The final holdout was opened once, after selection. No parameter was changed
  after it was opened.

## Candidate selection

| Candidate | Selection MAE | Zero Brier | High-cover Brier | Interval coverage | Mean interval width |
|---|---:|---:|---:|---:|---:|
| Campus, 120 min | $6.51 | 0.1049 | 0.2175 | 80.10% | $15.37 |
| Venue pooled, 60 min | **$6.24** | 0.1012 | 0.2131 | 82.12% | $15.74 |
| Venue pooled, 90 min | $6.39 | 0.1005 | 0.2134 | 82.29% | $15.85 |
| Venue pooled, 120 min | $6.35 | 0.1009 | 0.2143 | 82.29% | $15.82 |

The 60-minute venue-pooled candidate wins the declared primary metric. The
campus-only challenger establishes that the venue effect earns its place, but
the improvement is modest rather than transformative.

## Final holdout

| Metric | Result |
|---|---:|
| Observations | 260 |
| MAE | $7.50 |
| RMSE | $9.23 |
| Zero-cover Brier | 0.0865 |
| High-cover Brier | 0.2492 |
| Likely-interval coverage | 79.23% |
| Mean likely-interval width | $16.94 |
| Mean interval score | $23.87 |

Venue MAE is $8.20 at Brothers, $7.02 at Joe's, $7.27 at KAMS, and $6.96 at
Red Lion. Time-slice MAE ranges from $6.69 before 8 PM to $8.04 after midnight.
These are fallback-estimate errors on sparse community observations, not a
claim about official venue prices.

## Same-night nowcast

The v1 nowcast computes residuals against the historical prediction, keeps at
most the latest observation per actor and venue, decays evidence continuously,
shrinks sparse evidence, and clamps the result. The venue adjustment is capped
at $10. The campus factor:

- excludes the target venue already represented by its venue residual;
- requires at least two other venues;
- combines venue aggregates rather than raw reports;
- is scaled by 0.5 and capped at $5.

On the 96 final-holdout observations with an earlier same-venue report that
night, historical-only MAE is $8.18, venue-nowcast MAE is $7.97, and bounded
venue-plus-campus MAE is $7.60. Forty-three cases have enough other-venue
evidence for a campus factor. This ablation is encouraging but limited: source
records lack actor/trust provenance, so each record key stands in for an
independent actor only during this evaluation.

## Live resolver policy

Recovered historical data cannot choose live trust or conflict thresholds. The
v1 pure resolver therefore exposes the live horizon as a required caller input
and uses these conservative, replaceable interpretation defaults:

- 30-minute recency half-life inside the caller's horizon;
- latest report per actor as the independent live contribution;
- one ordinary manual/direct report can establish Live;
- a singleton untouched exact historical-model echo cannot establish Live;
- two independent echo confirmations, or an independent report at that price,
  can admit the echo;
- a second price becomes a range only when its weighted support is at least 60%
  of the leader and differs by at least $5;
- affirmative abuse can exclude evidence, while missing location, guest status,
  and new-install status remain neutral.

For beta integration the recommended caller horizon is 3,600 seconds, matching
the existing product behavior cited by the specification. That is a product
policy, not an empirically learned constant, and it is deliberately absent from
the schema and pure resolver.

## Retrospective Time Machine

Time Machine uses a small discrete price path over the target service night.
Observation quality controls emission cost; a penalty discourages unnecessary
state changes; the historical prediction is a weak prior. A current/as-of query
only sees evidence available at its cutoff. A retrospective query may use later
same-night reports, so an isolated earlier outlier can be smoothed away after
coherent later evidence arrives. The derived path is never fed back into
historical training.

## Initial release gates and limits

The first beta release meets the following operational guardrails:

- it beats the campus-only selection MAE;
- final-holdout MAE is no more than $8;
- likely-interval coverage is at least 70% with mean width no more than $20;
- no venue holdout MAE exceeds $10;
- bounded full nowcast does not worsen the eligible sequential-holdout MAE;
- artifact round-trip and knowledge-cutoff tests reproduce decisions.

These guardrails were recorded during the initial model study, not
preregistered before the historical data was examined. They are release policy,
not independent proof of quality. Future challengers need fresh untouched data
or post-launch shadow outcomes; this holdout must not be described as untouched
again.

No context feature was admitted, so context ablation is not applicable. There
are not enough labeled special-event, trust, or official-price outcomes to make
separate claims. The checked-in JSON receipt contains the exact compact metrics,
and `covers.modeling.evaluation.release_evaluation` reproduces them from the
hashed release. Canonical JSON encoding (sorted keys, compact separators,
UTF-8, no non-finite floats) hashes the full generated evaluation to
`6f2ab9fa650e095b46798837a0c51aaf0ffed3a7a9b7e466648786980525cc72`.

## Backend integration surface

All code is pure Python under `server/covers/modeling` and imports no Django
module.

1. Convert immutable ORM rows to `ObservationInput`; use the installation actor
   UUID as `actor_independence_key` and pass only derived distance/accuracy as
   `LocationContext`.
2. Convert admitted completed-night rows to `HistoricalObservation`, fit or load
   `HistoricalModel`, and persist `to_artifact()` with the release receipt.
3. Call `compute_nowcast(...)` for the explicit target/cutoff and pass its
   `NowcastAdjustment` to `resolve_cover(...)`.
4. Pass `live_horizon_seconds=3600` from versioned application settings for the
   initial beta; do not add it to database schema.
5. Persist `CoverResolution.receipt_summary()` plus the target time, knowledge
   cutoff, evidence/context revisions, and resolver version in the immutable
   `CoverDecision` row. `receipt_sha256()` provides the canonical hash; model
   artifacts expose the same guarantee through `artifact_sha256()`.
6. Call `cover_at(...)` for Time Machine. A target before cutoff performs
   retrospective reconstruction; a future target uses historical prediction and
   a same-service-night nowcast; target equal to cutoff is an as-of decision.

Public serialization should expose the price/source/status/freshness and
decision ID. Compact internal reasons and evidence IDs belong in restricted
receipt/debug data, not the public recent-report timeline.
