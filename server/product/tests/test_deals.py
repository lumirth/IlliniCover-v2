import uuid
from datetime import timedelta

import pytest
from covers.services import service_date_for
from deals.api import venue_deals
from deals.services import resolve_deal_evidence
from django.utils import timezone

from product.models import DealEvidenceEvent, DealFamily, HistoricalDealFact, Submission

NEW_GROUP = object()


def fact(venue, family, day, key, *, name="Wells", price=300):
    return HistoricalDealFact.objects.create(
        source_record_key=key,
        source="reviewed import",
        venue=venue,
        family=family,
        display_name=f"${price / 100:g} {name}",
        price_kind="single",
        price_cents=price,
        unit="each",
        service_date_local=day,
    )


def shape(family=None, *, name="Unreviewed words", price=300):
    return {
        "displayName": name,
        "category": "drink",
        "canonicalFamilyId": str(family.pk) if family else None,
        "priceKind": "single",
        "priceCents": price,
        "timingKnown": False,
        "whileSuppliesLast": False,
    }


def evidence(
    venue,
    day,
    action,
    *,
    target=None,
    submitted_shape=None,
    group=NEW_GROUP,
    minutes_ago=1,
    observed=None,
    received=None,
):
    observed = observed or timezone.now() - timedelta(minutes=minutes_ago)
    submission = Submission.objects.create(
        kind=Submission.Kind.DEAL_EVIDENCE,
        venue=venue,
        observed_at_client=observed,
        received_at_server=received or observed,
        independence_group=uuid.uuid4() if group is NEW_GROUP else group,
    )
    return DealEvidenceEvent.objects.create(
        submission=submission,
        action=action,
        target_id=target,
        submitted_shape=submitted_shape,
        service_date_local=day,
    )


@pytest.mark.django_db
def test_recurrence_uses_distinct_dates_and_ranks_stronger_cadence(venue):
    day = service_date_for(timezone.now())
    weak = DealFamily.objects.create(canonical_name="Weak", category="drink")
    strong = DealFamily.objects.create(canonical_name="Strong", category="drink")
    duplicate = DealFamily.objects.create(canonical_name="Duplicate", category="drink")
    for weeks in (1, 2):
        fact(venue, weak, day - timedelta(weeks=weeks), f"weak-{weeks}", name="Weak")
    for weeks in (1, 2, 3):
        fact(venue, strong, day - timedelta(weeks=weeks), f"strong-{weeks}", name="Strong")
    for index in range(3):
        fact(venue, duplicate, day - timedelta(weeks=1), f"duplicate-{index}", name="Duplicate")

    deals = venue_deals(venue, day)["deals"]
    assert [deal["canonical_family_id"] for deal in deals] == [strong.pk, weak.pk]


@pytest.mark.django_db
def test_arbitrary_custom_shape_stays_private(venue):
    day = service_date_for(timezone.now())
    custom = shape(name="Two-for-one mystery drink")
    evidence(venue, day, "ADD_MISSING", submitted_shape=custom)
    evidence(venue, day, "ADD_MISSING", submitted_shape=custom)
    assert resolve_deal_evidence(venue, day, []) == []


@pytest.mark.django_db
def test_reviewed_family_add_publishes_reviewed_text_with_stable_id(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    fact(venue, family, day - timedelta(weeks=1), "wells", name="Wells")
    submitted = shape(family, name="User supplied marketing copy")

    now = timezone.now()
    evidence(
        venue,
        day,
        "ADD_MISSING",
        submitted_shape=submitted,
        observed=now - timedelta(minutes=2),
    )
    earliest = evidence(
        venue,
        day,
        "ADD_MISSING",
        submitted_shape=submitted,
        observed=now - timedelta(minutes=3),
        received=now,
    )
    published = resolve_deal_evidence(venue, day, [])
    assert published[0]["id"] == earliest.pk
    assert published[0]["display_name"] == "Wells"
    assert published[0]["timing_known"] is False
    assert published[0]["timing_description"] is None

    evidence(venue, day, "ADD_MISSING", submitted_shape=submitted)
    assert resolve_deal_evidence(venue, day, [])[0]["id"] == earliest.pk


@pytest.mark.django_db
def test_distinct_shapes_do_not_corroborate_each_other(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    fact(venue, family, day - timedelta(weeks=1), "wells", name="Wells")
    evidence(venue, day, "ADD_MISSING", submitted_shape=shape(family, price=300))
    other = shape(family, price=300) | {"timingDescription": "Before 10", "timingKnown": True}
    evidence(venue, day, "ADD_MISSING", submitted_shape=other)
    assert resolve_deal_evidence(venue, day, []) == []


@pytest.mark.django_db
def test_confirm_and_deny_without_shapes_update_public_facts(venue):
    day = service_date_for(timezone.now())
    confirmed = DealFamily.objects.create(canonical_name="Confirmed", category="drink")
    denied = DealFamily.objects.create(canonical_name="Denied", category="drink")
    confirmed_target = denied_target = None
    for weeks in (1, 2):
        confirmed_fact = fact(
            venue,
            confirmed,
            day - timedelta(weeks=weeks),
            f"confirmed-{weeks}",
            name="Confirmed",
        )
        denied_fact = fact(
            venue,
            denied,
            day - timedelta(weeks=weeks),
            f"denied-{weeks}",
            name="Denied",
        )
        if weeks == 1:
            confirmed_target, denied_target = confirmed_fact, denied_fact

    actors = (uuid.uuid4(), uuid.uuid4())
    for actor in actors:
        evidence(venue, day, "CONFIRM_PRESENT", target=confirmed_target.pk, group=actor)
        evidence(venue, day, "DENY_PRESENT", target=denied_target.pk)
    deals = venue_deals(venue, day)["deals"]
    assert [(deal["canonical_family_id"], deal["status"]) for deal in deals] == [
        (confirmed.pk, "confirmed")
    ]

    for actor in actors:
        evidence(venue, day, "DENY_PRESENT", target=confirmed_target.pk, group=actor)
    assert venue_deals(venue, day)["deals"] == []


@pytest.mark.django_db
def test_delayed_older_confirm_cannot_override_newer_observed_denial(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = fact(venue, family, day - timedelta(weeks=1), "wells-1")
    fact(venue, family, day - timedelta(weeks=2), "wells-2")
    now = timezone.now()
    for actor in (uuid.uuid4(), uuid.uuid4()):
        evidence(
            venue,
            day,
            "DENY_PRESENT",
            target=target.pk,
            group=actor,
            observed=now - timedelta(minutes=1),
        )
        evidence(
            venue,
            day,
            "CONFIRM_PRESENT",
            target=target.pk,
            group=actor,
            observed=now - timedelta(minutes=10),
            received=now,
        )
    assert venue_deals(venue, day)["deals"] == []


@pytest.mark.django_db
def test_confirming_a_correction_preserves_its_shape_and_public_id(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    fact(venue, family, day - timedelta(weeks=1), "wells", name="Wells")
    actors = (uuid.uuid4(), uuid.uuid4())
    for actor in actors:
        evidence(venue, day, "ADD_MISSING", submitted_shape=shape(family), group=actor)
    target = resolve_deal_evidence(venue, day, [])[0]["id"]
    for actor in actors:
        evidence(
            venue,
            day,
            "CORRECT",
            target=target,
            submitted_shape=shape(family, price=400),
            group=actor,
        )
    result = resolve_deal_evidence(venue, day, [])
    assert len(result) == 1 and result[0]["id"] == target and result[0]["price_cents"] == 400

    for actor in actors:
        evidence(venue, day, "CONFIRM_PRESENT", target=target, group=actor)
    result = resolve_deal_evidence(venue, day, [])
    assert len(result) == 1 and result[0]["id"] == target and result[0]["price_cents"] == 400

    for actor in actors:
        evidence(
            venue,
            day,
            "CORRECT",
            target=target,
            submitted_shape=shape(family, price=500),
            group=actor,
        )
    assert resolve_deal_evidence(venue, day, [])[0]["price_cents"] == 500

    for actor in actors:
        evidence(venue, day, "DENY_PRESENT", target=target, group=actor)
    assert resolve_deal_evidence(venue, day, []) == []


@pytest.mark.django_db
def test_newer_observed_correction_beats_older_later_upload_candidate(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = fact(venue, family, day - timedelta(weeks=1), "wells")
    now = timezone.now()
    newer = now - timedelta(minutes=1)
    for _ in range(2):
        evidence(
            venue,
            day,
            "CORRECT",
            target=target.pk,
            submitted_shape=shape(family, price=500),
            observed=newer,
        )
    for _ in range(2):
        evidence(
            venue,
            day,
            "CORRECT",
            target=target.pk,
            submitted_shape=shape(family, price=400),
            observed=now - timedelta(minutes=10),
            received=now,
        )

    result = resolve_deal_evidence(venue, day, [])
    assert len(result) == 1 and result[0]["price_cents"] == 500
    assert result[0]["latest_activity_at"] == newer


@pytest.mark.django_db
def test_unpublishable_correction_does_not_hide_reviewed_deal(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = None
    for weeks in (1, 2):
        target = fact(venue, family, day - timedelta(weeks=weeks), f"wells-{weeks}")
    invalid = shape(family, price=400) | {"servingFormat": "unreviewed words"}
    for _ in range(2):
        evidence(venue, day, "CORRECT", target=target.pk, submitted_shape=invalid)
    assert venue_deals(venue, day)["deals"][0]["price_cents"] == 300


@pytest.mark.django_db
def test_corrections_to_different_targets_cannot_corroborate(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    fact(venue, family, day - timedelta(weeks=1), "wells", name="Wells")
    corrected = shape(family, price=400)
    evidence(
        venue,
        day,
        "CORRECT",
        target=uuid.uuid4(),
        submitted_shape=corrected,
    )
    evidence(
        venue,
        day,
        "CORRECT",
        target=uuid.uuid4(),
        submitted_shape=corrected,
    )
    assert resolve_deal_evidence(venue, day, []) == []


@pytest.mark.django_db
def test_erased_groups_neither_publish_nor_deny(venue):
    day = service_date_for(timezone.now())
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = None
    for weeks in (1, 2):
        current = fact(
            venue,
            family,
            day - timedelta(weeks=weeks),
            f"wells-{weeks}",
            name="Wells",
        )
        if weeks == 1:
            target = current
    submitted = shape(family)
    for _ in range(2):
        evidence(venue, day, "ADD_MISSING", submitted_shape=submitted, group=None)
        evidence(venue, day, "DENY_PRESENT", target=target.pk, group=None)

    deals = venue_deals(venue, day)["deals"]
    assert len(deals) == 1 and deals[0]["id"] == target.pk
