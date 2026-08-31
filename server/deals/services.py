from collections import defaultdict

from django.db import IntegrityError, transaction
from django.utils import timezone
from identity.attribution import submission_account_id
from product.models import (
    Account,
    DealEvidenceEvent,
    DealFamily,
    HistoricalDealFact,
    InstallationActor,
    Submission,
    SubmissionPrivateContext,
    Venue,
)
from submissions.rate_limits import enforce_submission_limits
from submissions.services import (
    IdempotencyConflict,
    UnknownVenue,
    location_values,
    lock_submission_identity,
    same_location,
    submission_trust,
)

from deals.names import public_deal_name


class InvalidDealTarget(Exception):
    pass


class InvalidServiceDate(Exception):
    pass


class InvalidDealFamily(Exception):
    pass


def serialize_deal(deal):
    return {
        "id": deal.pk,
        "canonical_family_id": deal.family_id,
        "display_name": deal.display_name,
        "category": deal.family.category,
        "price_kind": deal.price_kind,
        "price_cents": deal.price_cents,
        "price_low_cents": getattr(deal, "price_low_cents", None),
        "price_high_cents": getattr(deal, "price_high_cents", None),
        "discount_percent": float(deal.discount_percent)
        if deal.discount_percent is not None
        else None,
        "unit": deal.unit,
        "serving_format": getattr(deal, "serving_format", ""),
        "timing_description": getattr(deal, "timing_description", "") or None,
        "timing_known": bool(getattr(deal, "timing_description", "")),
        "while_supplies_last": deal.while_supplies_last,
        "status": getattr(deal, "status", "likely"),
        "latest_activity_at": None,
    }


def _reviewed_fact(shape, event):
    facts = HistoricalDealFact.objects.filter(
        family_id=shape.get("canonicalFamilyId"), family__category=shape["category"]
    ).select_related("family")
    if event.action == "CORRECT":
        target = facts.filter(pk=event.target_id, venue=event.submission.venue).first()
        if target:
            return target
        original = DealEvidenceEvent.objects.filter(
            pk=event.target_id, submission__venue=event.submission.venue
        ).first()
        original_shape = original.submitted_shape if original else None
        if not original_shape or (
            original_shape.get("canonicalFamilyId") != shape.get("canonicalFamilyId")
            or original_shape.get("category") != shape.get("category")
        ):
            return None
    return (
        facts.filter(venue=event.submission.venue).order_by("-service_date_local").first()
        or facts.order_by("-service_date_local").first()
    )


def _shape_deal(shape, event, public_id):
    fact = _reviewed_fact(shape, event)
    if (
        fact is None
        or shape.get("unit", "").casefold() not in {"", fact.unit.casefold()}
        or shape.get("servingFormat", "")
        or (
            shape.get("timingDescription", "")
            and shape["timingDescription"].casefold() != fact.timing_description.casefold()
        )
    ):
        return None
    return {
        "id": public_id,
        "canonical_family_id": shape.get("canonicalFamilyId"),
        "display_name": public_deal_name(
            fact.display_name,
            price_kind=fact.price_kind,
            price_cents=fact.price_cents,
            discount_percent=fact.discount_percent,
        ),
        "category": shape["category"],
        "price_kind": shape["priceKind"],
        "price_cents": shape.get("priceCents"),
        "price_low_cents": shape.get("priceLowCents"),
        "price_high_cents": shape.get("priceHighCents"),
        "discount_percent": shape.get("discountPercent"),
        "unit": fact.unit,
        "serving_format": "",
        "timing_description": (
            shape.get("timingDescription") or None if shape.get("timingKnown") else None
        ),
        "timing_known": shape.get("timingKnown", False),
        "while_supplies_last": shape.get("whileSuppliesLast", False),
        "status": "confirmed",
        "latest_activity_at": event.submission.observed_at_client,
    }


def _shape_key(event):
    shape = event.submitted_shape
    if not shape:
        return None
    fields = (
        "canonicalFamilyId",
        "category",
        "priceKind",
        "priceCents",
        "priceLowCents",
        "priceHighCents",
        "discountPercent",
        "timingKnown",
        "whileSuppliesLast",
        "unit",
        "servingFormat",
        "timingDescription",
    )
    return (
        event.action,
        event.target_id if event.action == "CORRECT" else None,
        *(str(shape.get(field)) for field in fields),
    )


def _deal_events(venue, service_date):
    now = timezone.now()
    events = list(
        DealEvidenceEvent.objects.filter(
            submission__venue=venue,
            service_date_local=service_date,
            submission__time_quality="plausible",
            submission__observed_at_client__lte=now,
            submission__received_at_server__lte=now,
        ).select_related("submission")
    )
    return [event for event in events if not event.submission.trust.get("impossibleMovement")]


def _event_order(event):
    submission = event.submission
    return (
        submission.observed_at_client,
        submission.received_at_server,
        str(event.pk),
    )


def _index_events(events):
    all_by_target = defaultdict(list)
    latest_by_actor = {}
    correction_by_actor = {}
    for event in sorted(events, key=_event_order):
        all_by_target[event.target_id].append(event)
        group = event.submission.independence_group
        if event.target_id and group:
            actor_target = (event.target_id, group)
            latest_by_actor[actor_target] = event
            if event.action == "CORRECT":
                correction_by_actor[actor_target] = event
            elif event.action == "DENY_PRESENT":
                correction_by_actor.pop(actor_target, None)
    by_target = defaultdict(list)
    for event in latest_by_actor.values():
        by_target[event.target_id].append(event)
    shapes = defaultdict(list)
    for event in events:
        group = event.submission.independence_group
        if not group:
            continue
        if event.action == "CORRECT" and correction_by_actor.get(
            (event.target_id, group)
        ) != event:
            continue
        key = _shape_key(event)
        if key:
            shapes[key].append(event)
    return all_by_target, by_target, shapes


def _shape_candidates(shapes, by_target):
    candidates: dict = {}
    for _, grouped in shapes.items():
        independent = {
            event.submission.independence_group
            for event in grouped
            if event.submission.independence_group
        }
        latest = max(grouped, key=_event_order)
        shape = latest.submitted_shape
        if not shape:
            continue
        identity = min(grouped, key=_event_order)
        public_id = latest.target_id or identity.pk
        denials = {
            event.submission.independence_group
            for event in by_target[public_id]
            if event.action == "DENY_PRESENT" and event.submission.independence_group
        }
        if shape.get("canonicalFamilyId") and len(independent) >= 2 and len(denials) < 2:
            shaped = _shape_deal(shape, latest, public_id)
            if shaped is not None:
                shaped["latest_activity_at"] = latest.submission.observed_at_client
                rank = (latest.action == "CORRECT", _event_order(latest))
                if public_id not in candidates or rank > candidates[public_id][0]:
                    candidates[public_id] = (rank, shaped)
    return candidates


def _visible_deals(deals, candidates, by_target, all_by_target):
    visible = []
    for deal in deals:
        if deal["id"] in candidates:
            continue
        votes = by_target[deal["id"]]
        confirmations = {
            row.submission.independence_group
            for row in votes
            if row.action == "CONFIRM_PRESENT" and row.submission.independence_group
        }
        denials = {
            row.submission.independence_group
            for row in votes
            if row.action == "DENY_PRESENT" and row.submission.independence_group
        }
        if len(denials) >= 2 and len(denials) > len(confirmations):
            continue
        activity = max(all_by_target[deal["id"]], key=_event_order, default=None)
        deal["latest_activity_at"] = activity.submission.observed_at_client if activity else None
        if len(confirmations) >= 2:
            deal["status"] = "confirmed"
        visible.append(deal)
    visible.extend(value[1] for value in candidates.values())
    return visible


def resolve_deal_evidence(venue, service_date, deals):
    all_by_target, by_target, shapes = _index_events(_deal_events(venue, service_date))
    return _visible_deals(
        deals, _shape_candidates(shapes, by_target), by_target, all_by_target
    )


def _receipt(event, duplicate):
    return {
        "submission_id": event.submission_id,
        "accepted_at": event.submission.received_at_server,
        "duplicate": duplicate,
    }


def _existing_receipt(existing, payload):
    event = getattr(existing, "deal_event", None)
    shape = (
        payload.submitted_deal_shape.model_dump(mode="json", by_alias=True)
        if payload.submitted_deal_shape
        else None
    )
    if not (
        existing.kind == Submission.Kind.DEAL_EVIDENCE
        and existing.venue_id == payload.venue_id
        and existing.observed_at_client == payload.observed_at
        and existing.vantage_point == payload.vantage_point
        and existing.client_platform == payload.client_platform
        and existing.entry_point == payload.entry_point
        and event
        and event.action == payload.action
        and event.target_id == payload.target_deal_id
        and event.submitted_shape == shape
        and event.service_date_local == payload.service_date_local
        and same_location(existing, payload.location)
    ):
        raise IdempotencyConflict
    return _receipt(event, True)


@transaction.atomic
def accept_deal_evidence(
    actor: InstallationActor,
    payload,
    *,
    remote_address: str | None,
    session_account: Account | None = None,
):
    existing = Submission.objects.filter(pk=payload.submission_id).first()
    if existing:
        return _existing_receipt(existing, payload)
    actor, session_account = lock_submission_identity(actor, session_account)
    account_id = submission_account_id(actor, session_account)
    venue = Venue.objects.filter(pk=payload.venue_id, is_active=True).first()
    if venue is None:
        raise UnknownVenue
    from covers.services import service_date_for

    if payload.service_date_local != service_date_for(payload.observed_at):
        raise InvalidServiceDate
    shape = payload.submitted_deal_shape
    if shape and shape.canonical_family_id and not DealFamily.objects.filter(
        pk=shape.canonical_family_id, category=shape.category
    ).exists():
        raise InvalidDealFamily
    target = payload.target_deal_id
    if target and not (
        HistoricalDealFact.objects.filter(pk=target, venue=venue).exists()
        or DealEvidenceEvent.objects.filter(
            pk=target, submission__venue=venue, submitted_shape__isnull=False
        ).exists()
    ):
        raise InvalidDealTarget
    enforce_submission_limits(
        actor,
        account_id=account_id,
        venue_id=venue.pk,
        remote_address=remote_address,
        now_seconds=int(timezone.now().timestamp()),
    )
    received = timezone.now()
    location = payload.location
    time_quality, trust = submission_trust(
        actor, payload, venue, received, signed_in=account_id is not None
    )
    try:
        with transaction.atomic():
            submission = Submission.objects.create(
                id=payload.submission_id,
                kind=Submission.Kind.DEAL_EVIDENCE,
                venue=venue,
                observed_at_client=payload.observed_at,
                received_at_server=received,
                time_quality=time_quality,
                vantage_point=payload.vantage_point,
                client_platform=payload.client_platform,
                entry_point=payload.entry_point,
                independence_group=account_id or actor.pk,
                trust=trust,
            )
    except IntegrityError:
        return _existing_receipt(Submission.objects.get(pk=payload.submission_id), payload)
    latitude, longitude, accuracy, permission = location_values(location)
    SubmissionPrivateContext.objects.create(
        submission=submission,
        actor=actor,
        account_id=account_id,
        latitude=latitude,
        longitude=longitude,
        location_accuracy_m=accuracy,
        location_permission=permission,
    )
    event = DealEvidenceEvent.objects.create(
        submission=submission,
        action=payload.action,
        target_id=target,
        submitted_shape=(
            payload.submitted_deal_shape.model_dump(mode="json", by_alias=True)
            if payload.submitted_deal_shape
            else None
        ),
        service_date_local=payload.service_date_local,
    )
    return _receipt(event, False)
