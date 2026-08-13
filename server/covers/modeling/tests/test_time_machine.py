from datetime import UTC, datetime, timedelta

from covers.modeling.time_machine import cover_at
from covers.modeling.types import (
    AdvertisedAdmissionInput,
    HistoricalPrediction,
    ObservationInput,
)


class FixedHistoricalModel:
    def predict(self, _venue_id, _target_time, *, knowledge_cutoff):
        del knowledge_cutoff
        return HistoricalPrediction(
            point_cents=1_000,
            low_cents=500,
            high_cents=1_500,
            probability_zero=0.1,
            probability_high=0.1,
            support=10,
            model_release="fixed-v1",
            probabilities={500: 0.1, 1_000: 0.8, 1_500: 0.1},
        )


def report(observation_id: str, actor: str, price: int, moment: datetime):
    return ObservationInput(
        observation_id=observation_id,
        venue_id="kams",
        actor_independence_key=actor,
        observed_at=moment,
        received_at=moment,
        price_cents=price,
    )


def admission(
    admission_id: str,
    price: int,
    *,
    available_at: datetime,
    starts_at: datetime,
    ends_at: datetime | None,
) -> AdvertisedAdmissionInput:
    return AdvertisedAdmissionInput(
        admission_id=admission_id,
        venue_id="kams",
        price_cents=price,
        available_at=available_at,
        starts_at=starts_at,
        ends_at=ends_at,
        is_unconditional=True,
    )


def test_as_of_decision_and_retrospective_reconstruction_can_differ():
    target = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
    initial = report("initial", "actor-a", 3_000, target)
    later_a = report("later-a", "actor-b", 1_000, target + timedelta(minutes=10))
    later_b = report("later-b", "actor-c", 1_000, target + timedelta(minutes=20))
    as_of = cover_at(
        venue_id="kams",
        target_time=target,
        knowledge_cutoff=target,
        observations=(initial, later_a, later_b),
        historical_model=FixedHistoricalModel(),
        live_horizon_seconds=3_600,
    )
    retrospective = cover_at(
        venue_id="kams",
        target_time=target,
        knowledge_cutoff=target + timedelta(minutes=30),
        observations=(initial, later_a, later_b),
        historical_model=FixedHistoricalModel(),
        live_horizon_seconds=3_600,
    )
    assert as_of.status == "live"
    assert as_of.amount_cents == 3_000
    assert retrospective.status == "reconstructed"
    assert retrospective.amount_cents == 1_000
    assert "later_same_night_evidence_allowed" in retrospective.reasons


def test_future_target_uses_historical_prediction_with_same_night_nowcast():
    cutoff = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
    target = cutoff + timedelta(minutes=30)
    result = cover_at(
        venue_id="kams",
        target_time=target,
        knowledge_cutoff=cutoff,
        observations=(
            report("a", "actor-a", 2_000, cutoff - timedelta(minutes=5)),
            report("b", "actor-b", 2_000, cutoff - timedelta(minutes=10)),
        ),
        historical_model=FixedHistoricalModel(),
        live_horizon_seconds=3_600,
    )
    assert result.source == "historical"
    assert result.status == "historical"
    assert result.amount_cents > 1_000
    assert result.venue_adjustment_cents > 0


def test_time_machine_uses_only_advertised_facts_known_by_its_cutoff():
    target = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
    cutoff = target + timedelta(minutes=30)
    known = admission(
        "known",
        2_000,
        available_at=target - timedelta(minutes=10),
        starts_at=target - timedelta(hours=1),
        ends_at=target + timedelta(hours=1),
    )
    learned_later = admission(
        "learned-later",
        3_000,
        available_at=cutoff + timedelta(seconds=1),
        starts_at=target - timedelta(hours=1),
        ends_at=target + timedelta(hours=1),
    )

    result = cover_at(
        venue_id="kams",
        target_time=target,
        knowledge_cutoff=cutoff,
        observations=(),
        advertised_admissions=(known, learned_later),
        historical_model=FixedHistoricalModel(),
        live_horizon_seconds=3_600,
    )

    assert result.source == "advertised"
    assert result.amount_cents == 2_000
    assert result.evidence_ids == ("advertised:known",)


def test_retrospective_reconstruction_excludes_evidence_received_after_cutoff():
    target = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
    cutoff = target + timedelta(minutes=30)
    initial = report("initial", "actor-a", 3_000, target)
    too_late = ObservationInput(
        observation_id="too-late",
        venue_id="kams",
        actor_independence_key="actor-b",
        observed_at=target + timedelta(minutes=10),
        received_at=cutoff + timedelta(seconds=1),
        price_cents=1_000,
    )
    result = cover_at(
        venue_id="kams",
        target_time=target,
        knowledge_cutoff=cutoff,
        observations=(initial, too_late),
        historical_model=FixedHistoricalModel(),
        live_horizon_seconds=3_600,
    )
    assert result.evidence_ids == ("initial",)
    assert result.amount_cents == 3_000
