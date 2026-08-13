from dataclasses import dataclass
from datetime import datetime, timedelta

from .service_night import require_aware
from .types import AdmissionClass, EvidenceAssessment, ObservationInput


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    future_clock_tolerance_seconds: int = 300
    nearby_distance_m: float = 250.0
    useful_location_accuracy_m: float = 100.0
    implausibly_far_distance_m: float = 5_000.0
    reduced_weight: float = 0.6
    nearby_multiplier: float = 1.15
    manual_correction_multiplier: float = 1.15
    mature_actor_multiplier: float = 1.05
    signed_in_multiplier: float = 1.03
    maximum_weight: float = 1.35


DEFAULT_TRUST_POLICY = TrustPolicy()


def assess_observation(
    observation: ObservationInput,
    *,
    knowledge_cutoff: datetime,
    policy: TrustPolicy = DEFAULT_TRUST_POLICY,
) -> EvidenceAssessment:
    """Assess one observation in context; this is not a permanent actor score."""

    require_aware(knowledge_cutoff)
    require_aware(observation.observed_at)
    require_aware(observation.received_at)
    reasons: list[str] = []

    if not observation.actor_independence_key:
        return _assessment(observation, AdmissionClass.REJECTED, 0.0, ["missing_actor_key"])
    if isinstance(observation.price_cents, bool) or not isinstance(observation.price_cents, int):
        return _assessment(observation, AdmissionClass.REJECTED, 0.0, ["invalid_price_type"])
    if observation.price_cents < 0:
        return _assessment(observation, AdmissionClass.REJECTED, 0.0, ["negative_price"])
    if observation.received_at > knowledge_cutoff:
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["received_after_cutoff"])
    if observation.observed_at > knowledge_cutoff + timedelta(
        seconds=policy.future_clock_tolerance_seconds
    ):
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["future_observation_time"])
    if observation.severe_clock_manipulation:
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["severe_clock_manipulation"])
    if observation.hard_abuse or observation.known_automation:
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["affirmative_abuse"])
    if observation.impossible_movement:
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["impossible_movement"])
    if observation.linked_account_stuffing:
        return _assessment(observation, AdmissionClass.EXCLUDED, 0.0, ["linked_account_stuffing"])

    weight = 1.0
    admission = AdmissionClass.NORMAL
    if observation.time_quality not in {"good", "server_verified"}:
        admission = AdmissionClass.REDUCED
        weight *= policy.reduced_weight
        reasons.append("uncertain_observation_time")
    if observation.rapid_spam:
        admission = AdmissionClass.REDUCED
        weight *= policy.reduced_weight
        reasons.append("rapid_submission_pattern")

    location = observation.location
    if location is None:
        reasons.append("location_absent_neutral")
    elif location.accuracy_m <= 0 or location.distance_to_venue_m < 0:
        admission = AdmissionClass.REDUCED
        weight *= policy.reduced_weight
        reasons.append("invalid_location_quality")
    elif location.accuracy_m <= policy.useful_location_accuracy_m:
        if location.distance_to_venue_m <= policy.nearby_distance_m:
            weight *= policy.nearby_multiplier
            reasons.append("accurate_nearby_location")
        elif location.distance_to_venue_m >= policy.implausibly_far_distance_m:
            admission = AdmissionClass.REDUCED
            weight *= policy.reduced_weight
            reasons.append("accurate_location_far_from_venue")
    else:
        reasons.append("imprecise_location_neutral")

    if observation.is_manual_correction:
        weight *= policy.manual_correction_multiplier
        reasons.append("manual_correction")
    if observation.installation_age_days is not None and observation.installation_age_days >= 30:
        weight *= policy.mature_actor_multiplier
        reasons.append("mature_installation")
    if observation.prior_corroborations >= 3:
        weight *= policy.mature_actor_multiplier
        reasons.append("prior_corroboration")
    if observation.signed_in:
        weight *= policy.signed_in_multiplier
        reasons.append("signed_in_small_positive")

    independent = not observation.is_untouched_historical_echo
    if not independent:
        reasons.append("untouched_historical_echo")
    if not reasons:
        reasons.append("ordinary_observation")
    return EvidenceAssessment(
        observation_id=observation.observation_id,
        admission=admission,
        weight=min(weight, policy.maximum_weight),
        independent_price_label=independent,
        reasons=tuple(reasons),
    )


def _assessment(
    observation: ObservationInput,
    admission: AdmissionClass,
    weight: float,
    reasons: list[str],
) -> EvidenceAssessment:
    return EvidenceAssessment(
        observation_id=observation.observation_id,
        admission=admission,
        weight=weight,
        independent_price_label=not observation.is_untouched_historical_echo,
        reasons=tuple(reasons),
    )
