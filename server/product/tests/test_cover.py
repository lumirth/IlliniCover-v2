import uuid
from datetime import UTC, datetime, timedelta

import pytest
from covers.services import (
    _historical,
    current_vibes,
    report_history,
    resolve_at,
    serialize_decision,
    service_date_for,
    service_minute,
)

from product.models import AdvertisedAdmission, Submission

MOMENT = datetime(2026, 8, 30, 2, tzinfo=UTC)
NEW_GROUP = object()


def report(
    venue,
    price,
    observed,
    *,
    received=None,
    group=NEW_GROUP,
    echo=None,
    time_quality="plausible",
    vibes=None,
    **trust,
):
    return Submission.objects.create(
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=observed,
        received_at_server=received or observed,
        time_quality=time_quality,
        independence_group=uuid.uuid4() if group is NEW_GROUP else group,
        cover_price_cents=price,
        cover_interaction="direct" if price is not None else "",
        cover_echo=echo or {},
        vibes=vibes or [],
        trust=trust,
    )


def history(venue, target, prices):
    for weeks, price in enumerate(prices, 1):
        past = target - timedelta(weeks=weeks)
        report(venue, price, past, received=past)


@pytest.mark.django_db
def test_service_night_cutoff_and_dst_are_continuous():
    before_cutoff = datetime.fromisoformat("2026-08-30T04:59:00-05:00")
    at_cutoff = datetime.fromisoformat("2026-08-30T05:00:00-05:00")
    assert service_date_for(before_cutoff).isoformat() == "2026-08-29"
    assert service_date_for(at_cutoff).isoformat() == "2026-08-30"

    first = datetime.fromisoformat("2026-11-01T01:30:00-05:00")
    second = datetime.fromisoformat("2026-11-01T01:30:00-06:00")
    assert service_minute(second) - service_minute(first) == 60


@pytest.mark.django_db
def test_cutoff_excludes_later_receipts(venue):
    cutoff = MOMENT + timedelta(minutes=10)
    report(venue, 500, MOMENT, received=MOMENT)
    report(venue, 3000, MOMENT, received=cutoff + timedelta(seconds=1))
    assert resolve_at(venue, cutoff, cutoff)[1:6] == (500, None, None, "live", "live")


@pytest.mark.django_db
def test_one_actor_has_one_current_vote_and_conflict_has_no_midpoint(venue):
    actor = uuid.uuid4()
    report(venue, 500, MOMENT - timedelta(minutes=3), group=actor)
    report(venue, 3000, MOMENT - timedelta(minutes=2), group=actor)
    report(venue, 1000, MOMENT - timedelta(minutes=1))

    decision = resolve_at(venue, MOMENT, MOMENT)
    assert decision[:6] == ("range", None, 1000, 3000, "mixed", "live_mixed")


@pytest.mark.django_db
def test_erasure_does_not_turn_one_actor_into_many_votes(venue):
    actor = uuid.uuid4()
    for minutes in (5, 4, 3):
        report(venue, 500, MOMENT - timedelta(minutes=minutes), group=actor)
    report(venue, 1000, MOMENT - timedelta(minutes=2))
    report(venue, 1000, MOMENT - timedelta(minutes=1))
    assert resolve_at(venue, MOMENT, MOMENT)[1] == 1000

    Submission.objects.filter(independence_group=actor).update(independence_group=None)
    assert resolve_at(venue, MOMENT, MOMENT)[1] == 1000


@pytest.mark.django_db
def test_impossible_movement_is_excluded(venue):
    report(venue, 1500, MOMENT - timedelta(minutes=1))
    report(venue, 7000, MOMENT, impossibleMovement=True)
    assert resolve_at(venue, MOMENT, MOMENT)[0:6] == (
        "single",
        1500,
        None,
        None,
        "live",
        "live",
    )


@pytest.mark.django_db
def test_historical_echo_needs_two_independent_actors(venue):
    history(venue, MOMENT, [1000, 1000])
    echo = {
        "pricePrefilled": True,
        "priceTouched": False,
        "displayedSource": "historical",
        "displayedPriceKind": "single",
        "displayedAmountCents": 1000,
    }
    report(venue, 1000, MOMENT - timedelta(minutes=2), echo=echo)
    assert resolve_at(venue, MOMENT, MOMENT)[4:6] == ("historical", "historical")

    report(venue, 1000, MOMENT - timedelta(minutes=1), echo=echo)
    assert resolve_at(venue, MOMENT, MOMENT)[0:6] == (
        "single",
        1000,
        None,
        None,
        "live",
        "live",
    )


@pytest.mark.django_db
def test_cluster_beats_one_outlier_and_newer_cluster_replaces_older(venue):
    for minutes in (20, 15, 10):
        report(venue, 1000, MOMENT - timedelta(minutes=minutes))
    report(venue, 3000, MOMENT - timedelta(minutes=1))
    assert resolve_at(venue, MOMENT, MOMENT)[1] == 1000

    Submission.objects.all().delete()
    for minutes in (55, 50, 45):
        report(venue, 1000, MOMENT - timedelta(minutes=minutes))
    for minutes in (2, 1):
        report(venue, 2000, MOMENT - timedelta(minutes=minutes))
    assert resolve_at(venue, MOMENT, MOMENT)[1] == 2000


@pytest.mark.django_db
def test_freshness_uses_observed_time_and_metadata_names_the_cutoff(venue):
    observed = MOMENT - timedelta(minutes=17)
    report(venue, 1000, observed, received=MOMENT - timedelta(minutes=1))
    result = serialize_decision(resolve_at(venue, MOMENT, MOMENT), MOMENT, MOMENT)
    assert result["freshness_seconds"] == 17 * 60
    assert result["computed_at"] == result["target_time"] == result["knowledge_cutoff"] == MOMENT


@pytest.mark.django_db
def test_history_does_not_train_on_target_night_and_past_is_reconstructed(venue):
    history(venue, MOMENT, [1000, 1000, 1000])
    report(venue, 3000, MOMENT - timedelta(minutes=10))
    assert _historical(venue, MOMENT, MOMENT + timedelta(minutes=30), adjust=False)[1] == 1000

    for minutes in (5, 10, 15):
        observed = MOMENT + timedelta(minutes=minutes)
        report(venue, 2000, observed, received=observed)
    decision = resolve_at(venue, MOMENT, MOMENT + timedelta(minutes=30))
    assert decision[0:6] == (
        "single",
        2000,
        None,
        None,
        "historical",
        "reconstructed",
    )


@pytest.mark.django_db
def test_same_night_nowcast_moves_a_historical_range(venue):
    history(venue, MOMENT, [0, 500, 1500, 2000])
    for minutes in (100, 90):
        report(venue, 2000, MOMENT - timedelta(minutes=minutes))

    assert _historical(venue, MOMENT, MOMENT, adjust=False)[:4] == (
        "range",
        None,
        500,
        2000,
    )
    assert resolve_at(venue, MOMENT, MOMENT)[:6] == (
        "range",
        None,
        1000,
        2500,
        "historical",
        "historical",
    )


@pytest.mark.django_db
def test_advertised_agreement_preserves_live_and_conflict_is_explicit(venue):
    report(venue, 2000, MOMENT - timedelta(minutes=1))
    admission = AdvertisedAdmission.objects.create(
        venue=venue,
        price_cents=2000,
        starts_at=MOMENT - timedelta(hours=1),
        ends_at=MOMENT + timedelta(hours=1),
        published_at=MOMENT - timedelta(days=1),
        provenance="venue announcement",
    )
    assert resolve_at(venue, MOMENT, MOMENT)[1:6] == (2000, None, None, "live", "live")

    admission.price_cents = 2500
    admission.save(update_fields=["price_cents"])
    assert resolve_at(venue, MOMENT, MOMENT)[:6] == (
        "range",
        None,
        2000,
        2500,
        "mixed",
        "advertised_conflict",
    )


@pytest.mark.django_db
def test_public_history_contains_only_latest_admitted_safe_observations(venue):
    actor = uuid.uuid4()
    report(venue, 500, MOMENT - timedelta(minutes=20), group=actor)
    report(venue, 1000, MOMENT - timedelta(minutes=10), group=actor)
    report(venue, 7000, MOMENT - timedelta(minutes=1), impossibleMovement=True)
    report(venue, 2500, MOMENT - timedelta(minutes=2), locationSignal="far")

    result = report_history(venue, moment=MOMENT, premium=False)
    assert result["access_tier"] == "limited" and not result["has_more"]
    assert [row["price_cents"] for row in result["reports"]] == [1000]
    assert set(result["reports"][0]) == {
        "observed_at",
        "received_at",
        "price_cents",
        "interaction",
        "broad_context",
        "vibes",
    }


@pytest.mark.django_db
def test_vibe_dimensions_have_independent_freshness(venue):
    report(
        venue,
        None,
        MOMENT - timedelta(minutes=40),
        vibes=[
            {"dimension": "line_length", "value": "long"},
            {"dimension": "crowd_level", "value": "packed"},
        ],
    )
    assert current_vibes(venue, now=MOMENT) == {
        "line_length": None,
        "line_speed": None,
        "crowd_level": "packed",
    }
