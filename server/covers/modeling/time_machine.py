from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .nowcast import DEFAULT_NOWCAST_CONFIG, NowcastConfig, compute_nowcast
from .resolver import (
    DEFAULT_RESOLVER_CONFIG,
    ResolverConfig,
    active_advertised_admissions,
    apply_advertised_admissions,
    resolve_cover,
)
from .service_night import same_service_night
from .trust import DEFAULT_TRUST_POLICY, TrustPolicy, assess_observation
from .types import (
    AdmissionClass,
    AdvertisedAdmissionInput,
    CoverResolution,
    EvidenceAssessment,
    HistoricalPrediction,
    ObservationInput,
)


class HistoricalPredictor(Protocol):
    def predict(
        self,
        venue_id: str,
        target_time: datetime,
        knowledge_cutoff: datetime,
    ) -> HistoricalPrediction | None: ...


@dataclass(frozen=True, slots=True)
class ReconstructionConfig:
    actor_bucket_seconds: int = 1_800
    baseline_prior_per_500: float = 0.12
    observation_outlier_cost: float = 6.0
    transition_base_cost: float = 4.0
    transition_per_500: float = 0.75
    transition_decay_seconds: float = 7_200.0

    def __post_init__(self) -> None:
        if self.actor_bucket_seconds <= 0:
            raise ValueError("actor reconstruction bucket must be positive")
        if self.observation_outlier_cost <= 0:
            raise ValueError("observation outlier cost must be positive")
        if self.transition_base_cost < 0 or self.transition_per_500 < 0:
            raise ValueError("transition costs cannot be negative")


DEFAULT_RECONSTRUCTION_CONFIG = ReconstructionConfig()


@dataclass(frozen=True, slots=True)
class _AssessedObservation:
    observation: ObservationInput
    assessment: EvidenceAssessment


def cover_at(
    *,
    venue_id: str,
    target_time: datetime,
    knowledge_cutoff: datetime,
    observations: Iterable[ObservationInput],
    advertised_admissions: Iterable[AdvertisedAdmissionInput] = (),
    historical_model: HistoricalPredictor,
    live_horizon_seconds: int,
    resolver_config: ResolverConfig = DEFAULT_RESOLVER_CONFIG,
    nowcast_config: NowcastConfig = DEFAULT_NOWCAST_CONFIG,
    reconstruction_config: ReconstructionConfig = DEFAULT_RECONSTRUCTION_CONFIG,
    trust_policy: TrustPolicy = DEFAULT_TRUST_POLICY,
) -> CoverResolution:
    """Compute current, future, as-of, or retrospective Time Machine cover."""

    values = tuple(observations)
    advertised = active_advertised_admissions(
        venue_id=venue_id,
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        admissions=advertised_admissions,
    )

    def lookup(
        lookup_venue_id: str, lookup_time: datetime, lookup_cutoff: datetime
    ) -> HistoricalPrediction | None:
        return historical_model.predict(
            lookup_venue_id, lookup_time, knowledge_cutoff=lookup_cutoff
        )

    prediction = lookup(venue_id, target_time, knowledge_cutoff)
    if target_time < knowledge_cutoff:
        reconstructed = reconstruct_cover(
            venue_id=venue_id,
            target_time=target_time,
            knowledge_cutoff=knowledge_cutoff,
            observations=values,
            historical_lookup=lookup,
            config=reconstruction_config,
            trust_policy=trust_policy,
        )
        return apply_advertised_admissions(
            reconstructed,
            advertised,
            target_time=target_time,
        )

    nowcast = compute_nowcast(
        target_venue_id=venue_id,
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        observations=values,
        historical_lookup=lookup,
        config=nowcast_config,
        trust_policy=trust_policy,
    )
    return resolve_cover(
        venue_id=venue_id,
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        observations=values,
        advertised_admissions=advertised,
        historical_prediction=prediction,
        nowcast=nowcast,
        live_horizon_seconds=live_horizon_seconds,
        config=resolver_config,
        trust_policy=trust_policy,
    )


def reconstruct_cover(
    *,
    venue_id: str,
    target_time: datetime,
    knowledge_cutoff: datetime,
    observations: Iterable[ObservationInput],
    historical_lookup: Callable[[str, datetime, datetime], HistoricalPrediction | None],
    config: ReconstructionConfig = DEFAULT_RECONSTRUCTION_CONFIG,
    trust_policy: TrustPolicy = DEFAULT_TRUST_POLICY,
) -> CoverResolution:
    """Infer a conservative same-night price path using evidence known by cutoff."""

    if target_time > knowledge_cutoff:
        raise ValueError("retrospective reconstruction target must not exceed cutoff")
    values = [
        observation
        for observation in observations
        if observation.venue_id == venue_id
        and observation.observed_at <= knowledge_cutoff
        and observation.received_at <= knowledge_cutoff
        and same_service_night(observation.observed_at, target_time)
    ]

    # Repeated activity from one actor remains useful across a night, but cannot
    # multiply support inside a short time bucket.
    latest_by_actor_bucket: dict[tuple[str, int], _AssessedObservation] = {}
    for observation in sorted(
        values,
        key=lambda value: (
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
        bucket = int(observation.observed_at.timestamp()) // config.actor_bucket_seconds
        key = (observation.actor_independence_key, bucket)
        incumbent = latest_by_actor_bucket.get(key)
        if incumbent is None or _observation_order(observation) > _observation_order(
            incumbent.observation
        ):
            latest_by_actor_bucket[key] = _AssessedObservation(observation, assessment)

    assessed: list[_AssessedObservation] = []
    echo_actors_by_price: dict[int, set[str]] = defaultdict(set)
    for _, item in sorted(latest_by_actor_bucket.items()):
        if not item.assessment.independent_price_label:
            echo_actors_by_price[item.observation.price_cents].add(
                item.observation.actor_independence_key
            )
        assessed.append(item)
    assessed = [
        item
        for item in assessed
        if item.assessment.independent_price_label
        or len(echo_actors_by_price[item.observation.price_cents]) >= 2
    ]

    baseline_at_target = historical_lookup(venue_id, target_time, knowledge_cutoff)
    if not assessed:
        return _baseline_reconstruction(baseline_at_target, "no_retrospective_live_evidence")

    by_time: dict[datetime, list[_AssessedObservation]] = defaultdict(list)
    for item in assessed:
        by_time[item.observation.observed_at].append(item)
    timeline = sorted({target_time, *by_time})
    baselines = {
        moment: historical_lookup(venue_id, moment, knowledge_cutoff) for moment in timeline
    }
    states = _candidate_states(assessed, tuple(baselines.values()))
    costs: list[dict[int, float]] = []
    parents: list[dict[int, int | None]] = []

    for index, moment in enumerate(timeline):
        local_cost = {
            state: _local_cost(
                state,
                by_time.get(moment, []),
                baselines[moment],
                config,
            )
            for state in states
        }
        if index == 0:
            costs.append(local_cost)
            parents.append({state: None for state in states})
            continue
        gap_seconds = max(0.0, (moment - timeline[index - 1]).total_seconds())
        current_costs: dict[int, float] = {}
        current_parents: dict[int, int | None] = {}
        for state in states:
            previous_cost, previous_state = min(
                (
                    costs[index - 1][prior_state]
                    + _transition_cost(prior_state, state, gap_seconds, config),
                    prior_state,
                )
                for prior_state in states
            )
            current_costs[state] = previous_cost + local_cost[state]
            current_parents[state] = previous_state
        costs.append(current_costs)
        parents.append(current_parents)

    end_state = min(costs[-1], key=costs[-1].__getitem__)
    path = [end_state]
    for index in range(len(timeline) - 1, 0, -1):
        parent = parents[index][path[-1]]
        if parent is None:
            raise RuntimeError("reconstruction path ended before the first state")
        path.append(parent)
    path.reverse()
    target_state = path[timeline.index(target_time)]
    target_baseline = baselines[target_time]
    evidence_ids = tuple(
        item.observation.observation_id
        for item in sorted(
            assessed,
            key=lambda value: (
                value.observation.observed_at,
                value.observation.observation_id,
            ),
        )
    )
    return CoverResolution(
        price_kind="single",
        amount_cents=target_state,
        low_cents=None,
        high_cents=None,
        source="historical",
        status="reconstructed",
        freshness_seconds=None,
        support=sum(item.assessment.weight for item in assessed),
        reasons=(
            "retrospective_price_path",
            "later_same_night_evidence_allowed",
            "knowledge_cutoff_applied",
        ),
        evidence_ids=evidence_ids,
        model_release=target_baseline.model_release if target_baseline else None,
    )


def _candidate_states(
    observations: list[_AssessedObservation],
    baselines: tuple[HistoricalPrediction | None, ...],
) -> tuple[int, ...]:
    states = {item.observation.price_cents for item in observations}
    for prediction in baselines:
        if prediction is None:
            continue
        states.update({prediction.point_cents, prediction.low_cents, prediction.high_cents})
        states.update(prediction.probabilities)
    if not states:
        states.add(0)
    return tuple(sorted(states))


def _local_cost(
    state: int,
    observations: list[_AssessedObservation],
    baseline: HistoricalPrediction | None,
    config: ReconstructionConfig,
) -> float:
    cost = 0.0
    if baseline is not None:
        cost += abs(state - baseline.point_cents) / 500.0 * config.baseline_prior_per_500
    for item in observations:
        distance = abs(state - item.observation.price_cents) / 500.0
        cost += item.assessment.weight * min(distance * distance, config.observation_outlier_cost)
    return cost


def _transition_cost(
    previous_state: int,
    state: int,
    gap_seconds: float,
    config: ReconstructionConfig,
) -> float:
    if previous_state == state:
        return 0.0
    change_cost = config.transition_base_cost + (
        abs(state - previous_state) / 500.0 * config.transition_per_500
    )
    # A change becomes more plausible over a long gap, but never free.
    gap_factor = max(0.35, math.exp(-gap_seconds / config.transition_decay_seconds))
    return change_cost * gap_factor


def _baseline_reconstruction(
    prediction: HistoricalPrediction | None, reason: str
) -> CoverResolution:
    if prediction is None:
        return CoverResolution(
            price_kind="unavailable",
            amount_cents=None,
            low_cents=None,
            high_cents=None,
            source="unavailable",
            status="unavailable",
            freshness_seconds=None,
            support=0.0,
            reasons=(reason, "no_historical_prediction"),
        )
    return CoverResolution(
        price_kind="single",
        amount_cents=prediction.point_cents,
        low_cents=None,
        high_cents=None,
        source="historical",
        status="reconstructed",
        freshness_seconds=None,
        support=prediction.support,
        reasons=(reason, "historical_reconstruction_fallback"),
        model_release=prediction.model_release,
    )


def _observation_order(observation: ObservationInput) -> tuple[datetime, datetime, str]:
    return observation.observed_at, observation.received_at, observation.observation_id
