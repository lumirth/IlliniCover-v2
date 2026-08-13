from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .trust import DEFAULT_TRUST_POLICY, TrustPolicy, assess_observation
from .types import (
    AdmissionClass,
    AdvertisedAdmissionInput,
    CoverResolution,
    EvidenceAssessment,
    HistoricalPrediction,
    NowcastAdjustment,
    ObservationInput,
)


@dataclass(frozen=True, slots=True)
class ResolverConfig:
    recency_half_life_seconds: float = 1_800.0
    material_conflict_ratio: float = 0.6
    minimum_conflict_distance_cents: int = 500

    def __post_init__(self) -> None:
        if self.recency_half_life_seconds <= 0:
            raise ValueError("resolver recency half-life must be positive")
        if not 0 < self.material_conflict_ratio <= 1:
            raise ValueError("material conflict ratio must be in (0, 1]")
        if self.minimum_conflict_distance_cents < 0:
            raise ValueError("minimum conflict distance cannot be negative")


DEFAULT_RESOLVER_CONFIG = ResolverConfig()
EMPTY_NOWCAST_ADJUSTMENT = NowcastAdjustment()


@dataclass(frozen=True, slots=True)
class _Evidence:
    observation: ObservationInput
    assessment: EvidenceAssessment
    recency_weight: float

    @property
    def weight(self) -> float:
        return self.assessment.weight * self.recency_weight


def resolve_cover(
    *,
    venue_id: str,
    target_time: datetime,
    knowledge_cutoff: datetime,
    observations: Iterable[ObservationInput],
    advertised_admissions: Iterable[AdvertisedAdmissionInput] = (),
    historical_prediction: HistoricalPrediction | None,
    nowcast: NowcastAdjustment = EMPTY_NOWCAST_ADJUSTMENT,
    live_horizon_seconds: int,
    config: ResolverConfig = DEFAULT_RESOLVER_CONFIG,
    trust_policy: TrustPolicy = DEFAULT_TRUST_POLICY,
) -> CoverResolution:
    """Resolve one current/as-of answer from live evidence or historical fallback.

    ``live_horizon_seconds`` is deliberately supplied by the caller and is not a
    schema or module constant. Future targets use the historical+nowcast path; live
    reports remain current evidence rather than facts about a future price.
    """

    if live_horizon_seconds <= 0:
        raise ValueError("live horizon must be positive")
    advertised = active_advertised_admissions(
        venue_id=venue_id,
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        admissions=advertised_admissions,
    )
    if target_time > knowledge_cutoff:
        return apply_advertised_admissions(
            _historical_resolution(historical_prediction, nowcast),
            advertised,
            target_time=target_time,
        )

    observation_values = tuple(observations)
    candidate_count = 0
    latest_by_actor: dict[str, _Evidence] = {}
    for observation in observation_values:
        if observation.venue_id != venue_id:
            continue
        if observation.received_at > knowledge_cutoff:
            continue
        if observation.observed_at > target_time:
            continue
        age_seconds = (target_time - observation.observed_at).total_seconds()
        if age_seconds < 0 or age_seconds > live_horizon_seconds:
            continue
        assessment = assess_observation(
            observation, knowledge_cutoff=knowledge_cutoff, policy=trust_policy
        )
        if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
            continue
        recency = math.exp(-math.log(2.0) * age_seconds / config.recency_half_life_seconds)
        evidence = _Evidence(observation, assessment, recency)
        candidate_count += 1
        incumbent = latest_by_actor.get(observation.actor_independence_key)
        if incumbent is None or _observation_order(observation) > _observation_order(
            incumbent.observation
        ):
            latest_by_actor[observation.actor_independence_key] = evidence

    assessed = [evidence for _, evidence in sorted(latest_by_actor.items())]

    independent_prices = {
        evidence.observation.price_cents
        for evidence in assessed
        if evidence.assessment.independent_price_label
    }
    echo_actors_by_price: dict[int, set[str]] = defaultdict(set)
    for evidence in assessed:
        if not evidence.assessment.independent_price_label:
            echo_actors_by_price[evidence.observation.price_cents].add(
                evidence.observation.actor_independence_key
            )
    admitted: list[_Evidence] = []
    for evidence in assessed:
        if evidence.assessment.independent_price_label:
            admitted.append(evidence)
            continue
        price = evidence.observation.price_cents
        if price in independent_prices or len(echo_actors_by_price[price]) >= 2:
            admitted.append(evidence)

    if not admitted:
        fallback = _historical_resolution(historical_prediction, nowcast)
        if assessed and fallback.source != "unavailable":
            fallback = _replace_reasons(
                fallback, ("singleton_model_echo_ignored", *fallback.reasons)
            )
        return apply_advertised_admissions(fallback, advertised, target_time=target_time)

    support_by_price: dict[int, float] = defaultdict(float)
    for evidence in admitted:
        support_by_price[evidence.observation.price_cents] += evidence.weight

    ranked = sorted(support_by_price.items(), key=lambda item: (-item[1], item[0]))
    leading_price, leading_support = ranked[0]
    material_prices = [leading_price]
    for price, support in ranked[1:]:
        if (
            support >= leading_support * config.material_conflict_ratio
            and abs(price - leading_price) >= config.minimum_conflict_distance_cents
        ):
            material_prices.append(price)

    freshest = max(evidence.observation.observed_at for evidence in admitted)
    freshness = max(0, int((target_time - freshest).total_seconds()))
    total_support = sum(evidence.weight for evidence in admitted)
    evidence_ids = tuple(
        evidence.observation.observation_id
        for evidence in sorted(
            admitted,
            key=lambda item: (item.observation.observed_at, item.observation.observation_id),
        )
    )
    all_reduced = all(
        evidence.assessment.admission == AdmissionClass.REDUCED for evidence in admitted
    )

    if len(material_prices) > 1:
        live_resolution = CoverResolution(
            price_kind="range",
            amount_cents=None,
            low_cents=min(material_prices),
            high_cents=max(material_prices),
            source="mixed",
            status="live_mixed",
            freshness_seconds=freshness,
            support=total_support,
            reasons=("material_independent_conflict", "continuous_recency"),
            evidence_ids=evidence_ids,
        )
        return apply_advertised_admissions(
            live_resolution, advertised, target_time=target_time
        )

    source = "unconfirmed" if all_reduced else "live"
    status = "unconfirmed_unusual" if all_reduced else "live"
    reasons = ["ordinary_live_evidence", "continuous_recency"]
    if len(latest_by_actor) < candidate_count:
        reasons.append("actor_deduplicated")
    if echo_actors_by_price.get(leading_price):
        reasons.append("model_echo_corroborated")
    live_resolution = CoverResolution(
        price_kind="single",
        amount_cents=leading_price,
        low_cents=None,
        high_cents=None,
        source=source,
        status=status,
        freshness_seconds=freshness,
        support=total_support,
        reasons=tuple(reasons),
        evidence_ids=evidence_ids,
    )
    return apply_advertised_admissions(live_resolution, advertised, target_time=target_time)


def active_advertised_admissions(
    *,
    venue_id: str,
    target_time: datetime,
    knowledge_cutoff: datetime,
    admissions: Iterable[AdvertisedAdmissionInput],
) -> tuple[AdvertisedAdmissionInput, ...]:
    return tuple(
        sorted(
            (
                admission
                for admission in admissions
                if admission.venue_id == venue_id
                and admission.available_at <= knowledge_cutoff
                and admission.is_unconditional
                and not admission.qualification.strip()
                and admission.starts_at <= target_time
                and (admission.ends_at is None or target_time < admission.ends_at)
            ),
            key=lambda admission: (admission.price_cents, admission.admission_id),
        )
    )


def apply_advertised_admissions(
    resolution: CoverResolution,
    admissions: tuple[AdvertisedAdmissionInput, ...],
    *,
    target_time: datetime,
) -> CoverResolution:
    if not admissions:
        return resolution
    advertised_prices = {admission.price_cents for admission in admissions}
    evidence_ids = tuple(f"advertised:{admission.admission_id}" for admission in admissions)
    resolved_prices: set[int] = set()
    if resolution.price_kind == "single" and resolution.amount_cents is not None:
        resolved_prices.add(resolution.amount_cents)
    elif resolution.price_kind == "range":
        if resolution.low_cents is not None:
            resolved_prices.add(resolution.low_cents)
        if resolution.high_cents is not None:
            resolved_prices.add(resolution.high_cents)
    combined_prices = advertised_prices | resolved_prices
    if resolution.source in {"unavailable", "historical"} and len(advertised_prices) == 1:
        price = next(iter(advertised_prices))
        freshest_validation = max(admission.available_at for admission in admissions)
        return CoverResolution(
            price_kind="single",
            amount_cents=price,
            low_cents=None,
            high_cents=None,
            source="advertised",
            status="advertised",
            freshness_seconds=max(0, int((target_time - freshest_validation).total_seconds())),
            support=float(len(admissions)),
            reasons=("validated_unconditional_advertised_admission",),
            evidence_ids=evidence_ids,
            model_release=resolution.model_release,
            venue_adjustment_cents=resolution.venue_adjustment_cents,
            campus_adjustment_cents=resolution.campus_adjustment_cents,
        )
    if len(combined_prices) == 1:
        return _replace_reasons(
            resolution,
            (*resolution.reasons, "advertised_admission_agrees"),
        )
    return CoverResolution(
        price_kind="range",
        amount_cents=None,
        low_cents=min(combined_prices),
        high_cents=max(combined_prices),
        source="mixed",
        status="advertised_conflict",
        freshness_seconds=resolution.freshness_seconds,
        support=resolution.support + len(admissions),
        reasons=(*resolution.reasons, "advertised_admission_conflict"),
        evidence_ids=tuple((*resolution.evidence_ids, *evidence_ids)),
        model_release=resolution.model_release,
        venue_adjustment_cents=resolution.venue_adjustment_cents,
        campus_adjustment_cents=resolution.campus_adjustment_cents,
    )


def _historical_resolution(
    prediction: HistoricalPrediction | None,
    nowcast: NowcastAdjustment,
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
            reasons=("no_admitted_live_or_historical_evidence",),
        )
    delta = nowcast.total_delta_cents
    amount = _adjust_price(prediction.point_cents, delta)
    reasons = ["historical_fallback", *prediction.reasons]
    reasons.extend(nowcast.reasons)
    return CoverResolution(
        price_kind="single",
        amount_cents=amount,
        low_cents=None,
        high_cents=None,
        source="historical",
        status="historical",
        freshness_seconds=None,
        support=prediction.support + nowcast.venue_support + nowcast.campus_support,
        reasons=tuple(dict.fromkeys(reasons)),
        model_release=prediction.model_release,
        venue_adjustment_cents=nowcast.venue_delta_cents,
        campus_adjustment_cents=nowcast.campus_delta_cents,
    )


def _adjust_price(price_cents: int, delta_cents: int) -> int:
    return max(0, price_cents + delta_cents)


def _observation_order(observation: ObservationInput) -> tuple[datetime, datetime, str]:
    return observation.observed_at, observation.received_at, observation.observation_id


def _replace_reasons(resolution: CoverResolution, reasons: tuple[str, ...]) -> CoverResolution:
    return CoverResolution(
        price_kind=resolution.price_kind,
        amount_cents=resolution.amount_cents,
        low_cents=resolution.low_cents,
        high_cents=resolution.high_cents,
        source=resolution.source,
        status=resolution.status,
        freshness_seconds=resolution.freshness_seconds,
        support=resolution.support,
        reasons=reasons,
        evidence_ids=resolution.evidence_ids,
        model_release=resolution.model_release,
        venue_adjustment_cents=resolution.venue_adjustment_cents,
        campus_adjustment_cents=resolution.campus_adjustment_cents,
    )
