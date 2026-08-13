from datetime import UTC, datetime, timedelta

from covers.modeling.resolver import resolve_cover
from covers.modeling.trust import assess_observation
from covers.modeling.types import (
    AdmissionClass,
    AdvertisedAdmissionInput,
    HistoricalPrediction,
    LocationContext,
    ObservationInput,
)

TARGET = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)


def observation(
    observation_id: str,
    actor: str,
    price: int,
    *,
    minutes_ago: int = 0,
    **values,
) -> ObservationInput:
    observed_at = TARGET - timedelta(minutes=minutes_ago)
    return ObservationInput(
        observation_id=observation_id,
        venue_id="kams",
        actor_independence_key=actor,
        observed_at=observed_at,
        received_at=observed_at,
        price_cents=price,
        **values,
    )


def historical(price: int = 1_000) -> HistoricalPrediction:
    return HistoricalPrediction(
        point_cents=price,
        low_cents=500,
        high_cents=1_500,
        probability_zero=0.1,
        probability_high=0.2,
        support=10,
        model_release="test-release",
        probabilities={500: 0.2, price: 0.6, 1_500: 0.2},
    )


def resolve(*observations: ObservationInput, prediction=None):
    return resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=observations,
        historical_prediction=prediction,
        live_horizon_seconds=3_600,
    )


def advertised(
    admission_id: str,
    price: int,
    *,
    minutes_before: int = 10,
    minutes_after: int | None = 60,
    available_minutes_ago: int = 20,
    unconditional: bool = True,
    qualification: str = "",
) -> AdvertisedAdmissionInput:
    return AdvertisedAdmissionInput(
        admission_id=admission_id,
        venue_id="kams",
        price_cents=price,
        available_at=TARGET - timedelta(minutes=available_minutes_ago),
        starts_at=TARGET - timedelta(minutes=minutes_before),
        ends_at=(TARGET + timedelta(minutes=minutes_after) if minutes_after is not None else None),
        is_unconditional=unconditional,
        qualification=qualification,
    )


def test_missing_location_is_neutral_and_nearby_location_is_positive():
    ordinary = assess_observation(observation("a", "actor-a", 1_000), knowledge_cutoff=TARGET)
    nearby = assess_observation(
        observation(
            "b",
            "actor-b",
            1_000,
            location=LocationContext(distance_to_venue_m=25, accuracy_m=10),
        ),
        knowledge_cutoff=TARGET,
    )
    assert ordinary.admission == AdmissionClass.NORMAL
    assert ordinary.weight == 1.0
    assert "location_absent_neutral" in ordinary.reasons
    assert nearby.weight > ordinary.weight


def test_manual_correction_is_stronger_but_sign_in_is_only_small_positive():
    ordinary = assess_observation(observation("a", "actor-a", 2_000), knowledge_cutoff=TARGET)
    manual = assess_observation(
        observation(
            "b",
            "actor-b",
            2_000,
            price_touched=True,
            displayed_price_cents=1_000,
        ),
        knowledge_cutoff=TARGET,
    )
    signed_in = assess_observation(
        observation("c", "actor-c", 2_000, signed_in=True), knowledge_cutoff=TARGET
    )
    assert manual.weight > signed_in.weight > ordinary.weight


def test_affirmative_abuse_is_excluded_without_a_permanent_actor_score():
    result = assess_observation(
        observation("a", "actor-a", 1_000, impossible_movement=True),
        knowledge_cutoff=TARGET,
    )
    assert result.admission == AdmissionClass.EXCLUDED
    assert result.weight == 0


def test_one_ordinary_report_becomes_live():
    result = resolve(observation("a", "actor-a", 2_000), prediction=historical())
    assert result.source == "live"
    assert result.price_kind == "single"
    assert result.amount_cents == 2_000
    assert result.evidence_ids == ("a",)


def test_current_unconditional_advertised_admission_overrides_historical_fallback():
    result = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(),
        advertised_admissions=(advertised("door-sign", 2_000),),
        historical_prediction=historical(1_000),
        live_horizon_seconds=3_600,
    )

    assert result.source == "advertised"
    assert result.status == "advertised"
    assert result.amount_cents == 2_000
    assert result.evidence_ids == ("advertised:door-sign",)


def test_conditional_expired_and_future_admissions_never_become_universal_cover():
    facts = (
        advertised("conditional", 2_000, qualification="21+ only"),
        advertised("flagged-conditional", 2_000, unconditional=False),
        advertised("expired", 2_000, minutes_before=60, minutes_after=-1),
        advertised("future", 2_000, minutes_before=-5),
        advertised("not-yet-known", 2_000, available_minutes_ago=-1),
    )
    result = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(),
        advertised_admissions=facts,
        historical_prediction=historical(1_000),
        live_horizon_seconds=3_600,
    )

    assert result.source == "historical"
    assert result.amount_cents == 1_000


def test_advertised_freshness_comes_from_source_availability():
    result = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(),
        advertised_admissions=(
            advertised("older-source", 2_000, available_minutes_ago=20),
            advertised("fresh-source", 2_000, available_minutes_ago=3),
        ),
        historical_prediction=historical(),
        live_horizon_seconds=3_600,
    )

    assert result.source == "advertised"
    assert result.freshness_seconds == 180


def test_advertised_fact_agrees_with_live_or_surfaces_an_honest_conflict():
    agrees = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(observation("live", "actor", 2_000),),
        advertised_admissions=(advertised("sign", 2_000),),
        historical_prediction=historical(),
        live_horizon_seconds=3_600,
    )
    conflicts = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(observation("live", "actor", 1_000),),
        advertised_admissions=(advertised("sign", 2_000),),
        historical_prediction=historical(),
        live_horizon_seconds=3_600,
    )

    assert agrees.source == "live"
    assert agrees.amount_cents == 2_000
    assert "advertised_admission_agrees" in agrees.reasons
    assert conflicts.source == "mixed"
    assert conflicts.status == "advertised_conflict"
    assert (conflicts.low_cents, conflicts.high_cents) == (1_000, 2_000)


def test_singleton_model_echo_does_not_self_confirm_but_two_actors_can_confirm():
    echo_a = observation(
        "a",
        "actor-a",
        1_000,
        displayed_source="historical",
        displayed_price_cents=1_000,
        price_prefilled=True,
    )
    echo_b = observation(
        "b",
        "actor-b",
        1_000,
        displayed_source="historical",
        displayed_price_cents=1_000,
        price_prefilled=True,
    )
    singleton = resolve(echo_a, prediction=historical())
    corroborated = resolve(echo_a, echo_b, prediction=historical())
    assert singleton.source == "historical"
    assert "singleton_model_echo_ignored" in singleton.reasons
    assert corroborated.source == "live"
    assert corroborated.amount_cents == 1_000


def test_latest_report_per_actor_is_the_only_independent_vote():
    old = observation("old", "same-actor", 0, minutes_ago=20)
    new = observation("new", "same-actor", 2_000, minutes_ago=1)
    result = resolve(old, new)
    assert result.amount_cents == 2_000
    assert result.evidence_ids == ("new",)
    assert "actor_deduplicated" in result.reasons


def test_coherent_cluster_resists_one_outlier_and_newer_cluster_replaces_old():
    cluster = resolve(
        observation("a", "actor-a", 1_000, minutes_ago=5),
        observation("b", "actor-b", 1_000, minutes_ago=6),
        observation("outlier", "actor-c", 3_000, minutes_ago=1),
    )
    newer = resolve(
        observation("old-a", "actor-a", 1_000, minutes_ago=50),
        observation("old-b", "actor-b", 1_000, minutes_ago=49),
        observation("new-a", "actor-c", 2_000, minutes_ago=2),
        observation("new-b", "actor-d", 2_000, minutes_ago=1),
    )
    assert cluster.price_kind == "single"
    assert cluster.amount_cents == 1_000
    assert newer.amount_cents == 2_000


def test_two_materially_conflicting_reports_produce_a_range():
    result = resolve(
        observation("a", "actor-a", 1_000),
        observation("b", "actor-b", 2_000),
    )
    assert result.source == "mixed"
    assert result.status == "live_mixed"
    assert result.price_kind == "range"
    assert (result.low_cents, result.high_cents) == (1_000, 2_000)


def test_horizon_is_explicit_and_old_report_falls_back():
    old = observation("old", "actor-a", 2_000, minutes_ago=61)
    result = resolve_cover(
        venue_id="kams",
        target_time=TARGET,
        knowledge_cutoff=TARGET,
        observations=(old,),
        historical_prediction=historical(),
        live_horizon_seconds=3_600,
    )
    assert result.source == "historical"
    assert result.amount_cents == 1_000
    assert result.receipt_summary()["model_release"] == "test-release"


def test_report_received_after_cutoff_cannot_shadow_older_actor_evidence():
    old = observation("old", "same-actor", 1_000, minutes_ago=10)
    late_upload = ObservationInput(
        observation_id="late-upload",
        venue_id="kams",
        actor_independence_key="same-actor",
        observed_at=TARGET - timedelta(minutes=5),
        received_at=TARGET + timedelta(seconds=1),
        price_cents=3_000,
    )
    result = resolve(old, late_upload)
    assert result.source == "live"
    assert result.amount_cents == 1_000
    assert result.evidence_ids == ("old",)


def test_excluded_newer_observation_cannot_shadow_older_actor_evidence():
    old = observation("old", "same-actor", 1_000, minutes_ago=10)
    abusive = observation("abusive", "same-actor", 3_000, minutes_ago=5, impossible_movement=True)
    result = resolve(old, abusive)
    assert result.amount_cents == 1_000
    assert result.evidence_ids == ("old",)


def test_missing_actor_independence_key_is_rejected():
    result = assess_observation(observation("a", "", 1_000), knowledge_cutoff=TARGET)
    assert result.admission == AdmissionClass.REJECTED
    assert result.reasons == ("missing_actor_key",)


def test_compact_receipt_hash_is_stable():
    result = resolve(observation("a", "actor-a", 2_000))
    assert result.receipt_sha256() == (
        "b4003fdf7feddfb9a700c6fc4cfe36dd7ecfd59aef546fa8fa714760b67899bd"
    )


def test_receipt_hash_does_not_depend_on_input_order():
    first = observation("a", "actor-a", 2_000)
    second = observation("b", "actor-b", 2_000)
    assert resolve(first, second).receipt_sha256() == resolve(second, first).receipt_sha256()
