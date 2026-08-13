from datetime import UTC, date, datetime, timedelta

from covers.modeling.historical import HistoricalModel, HistoricalModelConfig
from covers.modeling.nowcast import NowcastConfig, compute_nowcast
from covers.modeling.service_night import (
    CHICAGO,
    service_date_for,
    service_minute,
    service_night_bounds,
)
from covers.modeling.types import HistoricalObservation, HistoricalPrediction, ObservationInput


def historical_row(
    observation_id: str,
    venue: str,
    moment: datetime,
    price: int,
    *,
    available_at: datetime | None = None,
) -> HistoricalObservation:
    return HistoricalObservation(
        observation_id=observation_id,
        venue_id=venue,
        observed_at=moment,
        available_at=available_at or moment,
        service_date=service_date_for(moment),
        price_cents=price,
    )


def test_service_night_cutoff_and_continuous_minutes():
    before_cutoff = datetime(2026, 8, 13, 9, 59, tzinfo=UTC)  # 04:59 Chicago
    at_cutoff = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)  # 05:00 Chicago
    assert service_date_for(before_cutoff) == date(2026, 8, 12)
    assert service_date_for(at_cutoff) == date(2026, 8, 13)
    assert service_minute(at_cutoff) == 0


def test_service_night_and_continuous_time_respect_dst_transitions():
    spring_start, spring_end = service_night_bounds(date(2026, 3, 7))
    fall_start, fall_end = service_night_bounds(date(2026, 10, 31))
    assert spring_end.timestamp() - spring_start.timestamp() == 23 * 3_600
    assert fall_end.timestamp() - fall_start.timestamp() == 25 * 3_600

    first_130 = datetime(2026, 11, 1, 1, 30, tzinfo=CHICAGO, fold=0)
    second_130 = datetime(2026, 11, 1, 1, 30, tzinfo=CHICAGO, fold=1)
    assert service_date_for(first_130) == service_date_for(second_130) == date(2026, 10, 31)
    assert service_minute(second_130) - service_minute(first_130) == 60


def test_historical_model_uses_continuous_time_and_venue_pooling():
    base = datetime(2026, 7, 31, 1, 0, tzinfo=UTC)
    rows = []
    for week in range(4):
        early = base - timedelta(days=7 * week)
        late = early + timedelta(hours=3)
        rows.extend(
            [
                historical_row(f"early-{week}", "kams", early, 500),
                historical_row(f"late-{week}", "kams", late, 2_000),
                historical_row(f"campus-{week}", "joes", early, 1_000),
            ]
        )
    model = HistoricalModel.fit(
        rows,
        HistoricalModelConfig(time_bandwidth_minutes=45, venue_pooling_strength=1),
    )
    cutoff = base + timedelta(days=8)
    early_prediction = model.predict("kams", base + timedelta(days=7), knowledge_cutoff=cutoff)
    late_prediction = model.predict(
        "kams", base + timedelta(days=7, hours=3), knowledge_cutoff=cutoff
    )
    assert early_prediction is not None and late_prediction is not None
    assert early_prediction.point_cents < late_prediction.point_cents
    assert "venue_partial_pooling" in early_prediction.reasons


def test_historical_prediction_does_not_leak_future_available_rows():
    old = datetime(2026, 6, 6, 3, 0, tzinfo=UTC)
    future = old + timedelta(days=7)
    model = HistoricalModel.fit(
        (
            historical_row("old", "kams", old, 500),
            historical_row("future", "kams", future, 2_500),
        )
    )
    before_future = model.predict("kams", future, knowledge_cutoff=future - timedelta(days=1))
    after_future = model.predict(
        "kams", future + timedelta(days=7), knowledge_cutoff=future + timedelta(days=8)
    )
    assert before_future is not None and after_future is not None
    assert before_future.probabilities.get(2_500, 0) == 0
    assert after_future.probabilities.get(2_500, 0) > 0


def test_historical_prediction_excludes_future_observed_row_even_if_available_is_bad():
    cutoff = datetime(2026, 7, 1, 3, 0, tzinfo=UTC)
    old = cutoff - timedelta(days=7)
    inconsistent_future = HistoricalObservation(
        observation_id="future-clock",
        venue_id="kams",
        observed_at=cutoff + timedelta(hours=1),
        available_at=cutoff - timedelta(seconds=1),
        service_date=service_date_for(old),
        price_cents=2_500,
    )
    model = HistoricalModel.fit((historical_row("old", "kams", old, 500), inconsistent_future))
    prediction = model.predict("kams", cutoff, knowledge_cutoff=cutoff)
    assert prediction is not None
    assert prediction.probabilities.get(2_500, 0) == 0


def test_historical_artifact_round_trip_is_reproducible():
    moment = datetime(2026, 7, 3, 3, 0, tzinfo=UTC)
    model = HistoricalModel.fit((historical_row("a", "kams", moment, 1_000),))
    restored = HistoricalModel.from_artifact(model.to_artifact())
    target = moment + timedelta(days=7)
    cutoff = target + timedelta(days=1)
    assert restored.predict("kams", target, knowledge_cutoff=cutoff) == model.predict(
        "kams", target, knowledge_cutoff=cutoff
    )
    assert restored.artifact_sha256() == model.artifact_sha256()


def baseline_lookup(_venue: str, _target: datetime, _cutoff: datetime):
    return HistoricalPrediction(
        point_cents=1_000,
        low_cents=500,
        high_cents=1_500,
        probability_zero=0.1,
        probability_high=0.1,
        support=10,
        model_release="baseline",
        probabilities={1_000: 1.0},
    )


def live_observation(
    observation_id: str, venue: str, actor: str, target: datetime, price: int, minutes: int
):
    moment = target - timedelta(minutes=minutes)
    return ObservationInput(
        observation_id=observation_id,
        venue_id=venue,
        actor_independence_key=actor,
        observed_at=moment,
        received_at=moment,
        price_cents=price,
    )


def test_venue_nowcast_strengthens_with_evidence_and_decays():
    target = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)
    recent = compute_nowcast(
        target_venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(
            live_observation("a", "kams", "a", target, 2_000, 5),
            live_observation("b", "kams", "b", target, 2_000, 10),
        ),
        historical_lookup=baseline_lookup,
    )
    old = compute_nowcast(
        target_venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(live_observation("a", "kams", "a", target, 2_000, 180),),
        historical_lookup=baseline_lookup,
    )
    assert recent.venue_delta_cents > old.venue_delta_cents >= 0
    assert recent.venue_delta_cents <= 1_000


def test_campus_factor_requires_multiple_other_venues_and_is_bounded():
    target = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)
    one_venue = compute_nowcast(
        target_venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(live_observation("a", "joes", "a", target, 5_000, 5),),
        historical_lookup=baseline_lookup,
    )
    campus = compute_nowcast(
        target_venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(
            live_observation("a", "joes", "a", target, 5_000, 5),
            live_observation("b", "red-lion", "b", target, 5_000, 5),
        ),
        historical_lookup=baseline_lookup,
        config=NowcastConfig(maximum_campus_adjustment_cents=500),
    )
    assert one_venue.campus_delta_cents == 0
    assert 0 < campus.campus_delta_cents <= 500


def test_nowcast_report_received_after_cutoff_cannot_shadow_eligible_actor_report():
    target = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)
    old = live_observation("old", "kams", "same", target, 2_000, 10)
    late = ObservationInput(
        observation_id="late",
        venue_id="kams",
        actor_independence_key="same",
        observed_at=target - timedelta(minutes=5),
        received_at=target + timedelta(seconds=1),
        price_cents=0,
    )
    result = compute_nowcast(
        target_venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(old, late),
        historical_lookup=baseline_lookup,
    )
    assert result.venue_delta_cents > 0
    assert result.venue_observation_count == 1
