from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from .service_night import same_service_night
from .trust import DEFAULT_TRUST_POLICY, TrustPolicy, assess_observation
from .types import (
    AdmissionClass,
    EvidenceAssessment,
    HistoricalPrediction,
    NowcastAdjustment,
    ObservationInput,
)

HistoricalLookup = Callable[[str, datetime, datetime], HistoricalPrediction | None]


@dataclass(frozen=True, slots=True)
class NowcastConfig:
    venue_half_life_seconds: float = 2_700.0
    campus_half_life_seconds: float = 3_600.0
    venue_shrinkage: float = 1.5
    campus_shrinkage: float = 3.0
    campus_scale: float = 0.5
    maximum_venue_adjustment_cents: int = 1_000
    maximum_campus_adjustment_cents: int = 500
    minimum_campus_venues: int = 2

    def __post_init__(self) -> None:
        if self.venue_half_life_seconds <= 0 or self.campus_half_life_seconds <= 0:
            raise ValueError("nowcast half-lives must be positive")
        if self.venue_shrinkage < 0 or self.campus_shrinkage < 0:
            raise ValueError("nowcast shrinkage cannot be negative")
        if not 0 <= self.campus_scale <= 1:
            raise ValueError("campus nowcast scale must be between zero and one")


DEFAULT_NOWCAST_CONFIG = NowcastConfig()


def compute_nowcast(
    *,
    target_venue_id: str,
    target_time: datetime,
    knowledge_cutoff: datetime,
    observations: Iterable[ObservationInput],
    historical_lookup: HistoricalLookup,
    config: NowcastConfig = DEFAULT_NOWCAST_CONFIG,
    trust_policy: TrustPolicy = DEFAULT_TRUST_POLICY,
) -> NowcastAdjustment:
    """Compute bounded same-service-night venue and campus residuals.

    Each actor contributes at most its latest observation per venue. The campus
    factor combines venue aggregates rather than individual reports, preventing a
    busy venue from becoming a pairwise-correlation substitute.
    """

    eligible = [
        observation
        for observation in observations
        if observation.observed_at <= min(target_time, knowledge_cutoff)
        and observation.received_at <= knowledge_cutoff
        and same_service_night(observation.observed_at, target_time)
    ]
    latest_by_actor_venue: dict[tuple[str, str], tuple[ObservationInput, EvidenceAssessment]] = {}
    for observation in sorted(
        eligible,
        key=lambda value: (
            value.venue_id,
            value.actor_independence_key,
            value.observed_at,
            value.observation_id,
        ),
    ):
        assessment = assess_observation(
            observation, knowledge_cutoff=knowledge_cutoff, policy=trust_policy
        )
        if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
            continue
        key = (observation.venue_id, observation.actor_independence_key)
        incumbent = latest_by_actor_venue.get(key)
        if incumbent is None or _observation_order(observation) > _observation_order(incumbent[0]):
            latest_by_actor_venue[key] = observation, assessment

    residuals_by_venue: dict[str, list[tuple[float, float]]] = defaultdict(list)
    observation_count_by_venue: dict[str, int] = defaultdict(int)
    for _, (observation, assessment) in sorted(latest_by_actor_venue.items()):
        if not assessment.independent_price_label:
            # An untouched model echo has no independent residual information.
            continue
        baseline = historical_lookup(
            observation.venue_id, observation.observed_at, observation.observed_at
        )
        if baseline is None:
            continue
        age_seconds = max(0.0, (target_time - observation.observed_at).total_seconds())
        half_life = (
            config.venue_half_life_seconds
            if observation.venue_id == target_venue_id
            else config.campus_half_life_seconds
        )
        recency = math.exp(-math.log(2.0) * age_seconds / half_life)
        weight = assessment.weight * recency
        if weight <= 1e-9:
            continue
        residuals_by_venue[observation.venue_id].append(
            (float(observation.price_cents - baseline.point_cents), weight)
        )
        observation_count_by_venue[observation.venue_id] += 1

    venue_delta = 0
    venue_support = 0.0
    target_residuals = residuals_by_venue.get(target_venue_id, [])
    if target_residuals:
        raw, venue_support = _weighted_mean(target_residuals)
        shrunken = raw * venue_support / (venue_support + config.venue_shrinkage)
        venue_delta = _bounded_dollar_value(shrunken, config.maximum_venue_adjustment_cents)

    # Own-venue evidence is already represented above, so it is excluded from the
    # campus factor. Requiring multiple other venues keeps the campus factor modest.
    campus_aggregates: list[tuple[float, float]] = []
    for venue_id, residuals in residuals_by_venue.items():
        if venue_id == target_venue_id:
            continue
        venue_mean, support = _weighted_mean(residuals)
        campus_aggregates.append((venue_mean, min(support, 1.5)))

    campus_delta = 0
    campus_support = 0.0
    if len(campus_aggregates) >= config.minimum_campus_venues:
        raw, campus_support = _weighted_mean(campus_aggregates)
        shrunken = (
            raw * config.campus_scale * campus_support / (campus_support + config.campus_shrinkage)
        )
        campus_delta = _bounded_dollar_value(shrunken, config.maximum_campus_adjustment_cents)

    reasons: list[str] = []
    if venue_delta:
        reasons.append("bounded_venue_residual")
    if campus_delta:
        reasons.append("bounded_multi_venue_campus_residual")
    if not reasons:
        reasons.append("insufficient_nowcast_residual")
    return NowcastAdjustment(
        venue_delta_cents=venue_delta,
        campus_delta_cents=campus_delta,
        venue_support=venue_support,
        campus_support=campus_support,
        venue_observation_count=observation_count_by_venue.get(target_venue_id, 0),
        campus_venue_count=len(campus_aggregates),
        reasons=tuple(reasons),
    )


def _weighted_mean(values: list[tuple[float, float]]) -> tuple[float, float]:
    support = sum(weight for _, weight in values)
    if support <= 0:
        return 0.0, 0.0
    return sum(value * weight for value, weight in values) / support, support


def _bounded_dollar_value(value: float, maximum_absolute_cents: int) -> int:
    bounded = max(-maximum_absolute_cents, min(maximum_absolute_cents, value))
    return int(round(bounded / 100.0) * 100)


def _observation_order(observation: ObservationInput) -> tuple[datetime, datetime, str]:
    return observation.observed_at, observation.received_at, observation.observation_id
