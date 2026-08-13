import hashlib
import hmac
import json
import uuid
from collections import defaultdict
from datetime import datetime

from covers.services import service_date_for
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from identity.attribution import submission_account_id
from identity.models import Account, ActorAccountLink, InstallationActor
from submissions.models import Submission, SubmissionPrivateContext
from submissions.rate_limits import enforce_submission_limits
from submissions.services import (
    IdempotencyConflict,
    UnknownVenue,
    classify_time_quality,
    lock_actor_lifecycle,
    lock_submission_id,
    network_verifier,
)
from venues.models import Venue

from deals.models import DealDefinition, DealEvidenceEvent, DealFamily, DealPrediction
from deals.names import public_deal_name
from deals.schemas import DealEvidenceInputSchema


class InvalidDealTarget(Exception):
    pass


class InvalidCorrectionLineage(Exception):
    pass


class InvalidServiceDate(Exception):
    pass


def evidence_fingerprint(payload: DealEvidenceInputSchema) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")
    )
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"accepted-deal-evidence-payload-v1:{canonical}".encode(),
        hashlib.sha256,
    ).hexdigest()


def event_receipt(submission: Submission, duplicate: bool) -> dict:
    event = submission.deal_evidence_event
    return {
        "submission_id": submission.id,
        "event_id": event.id,
        "accepted_at": submission.received_at_server,
        "duplicate": duplicate,
    }


def _receipt_for_existing(
    existing: Submission, payload: DealEvidenceInputSchema, fingerprint: str
) -> dict:
    if (
        existing.request_fingerprint != fingerprint
        or existing.kind != Submission.Kind.DEAL_EVIDENCE
    ):
        raise IdempotencyConflict
    return event_receipt(existing, duplicate=True)


@transaction.atomic
def accept_deal_evidence(
    actor: InstallationActor,
    payload: DealEvidenceInputSchema,
    *,
    remote_address: str | None,
    session_account: Account | None = None,
) -> dict:
    fingerprint = evidence_fingerprint(payload)
    lock_submission_id(payload.submission_id)
    existing = Submission.objects.filter(pk=payload.submission_id).first()
    if existing:
        return _receipt_for_existing(existing, payload, fingerprint)
    actor = lock_actor_lifecycle(actor.pk)
    account_id = submission_account_id(actor, session_account)
    venue = Venue.objects.filter(pk=payload.venue_id, is_active=True).first()
    if venue is None:
        raise UnknownVenue
    received_at = timezone.now()
    derived_service_date = service_date_for(payload.observed_at)
    if payload.service_date_local != derived_service_date:
        raise InvalidServiceDate
    if (
        payload.target_local_datetime is not None
        and service_date_for(payload.target_local_datetime) != derived_service_date
    ):
        raise InvalidServiceDate
    enforce_submission_limits(
        actor,
        account_id=account_id,
        venue_id=venue.id,
        remote_address=remote_address,
        now_seconds=int(received_at.timestamp()),
    )
    supersedes = None
    if payload.supersedes_event_id:
        supersedes = (
            DealEvidenceEvent.objects.select_related("submission", "submission__private_context")
            .filter(pk=payload.supersedes_event_id, submission__venue=venue)
            .first()
        )
        if supersedes is None:
            raise InvalidCorrectionLineage
        try:
            superseded_context = supersedes.submission.private_context
        except SubmissionPrivateContext.DoesNotExist as error:
            raise InvalidCorrectionLineage from error
        owns_superseded = (
            account_id is not None and superseded_context.account_id == account_id
        ) or (
            account_id is None
            and superseded_context.account_id is None
            and superseded_context.actor_id == actor.id
        )
        if not owns_superseded:
            # Cross-contributor corrections are valid new proposals, but they
            # cannot erase another person's evidence before corroboration.
            supersedes = None
    target = None
    target_evidence = None
    if payload.target_deal_id:
        target = DealDefinition.objects.filter(pk=payload.target_deal_id, venue=venue).first()
        if target is None:
            target_evidence = (
                DealEvidenceEvent.objects.select_related("submission")
                .filter(
                    pk=payload.target_deal_id,
                    submission__venue=venue,
                    service_date_local=payload.service_date_local,
                )
                .first()
            )
            if target_evidence is None:
                raise InvalidDealTarget
    target_prediction = None
    if payload.target_prediction_id:
        target_prediction = DealPrediction.objects.filter(
            pk=payload.target_prediction_id,
            venue=venue,
            service_date_local=payload.service_date_local,
        ).first()
        if target_prediction is None:
            raise InvalidDealTarget
        if target is not None and target_prediction.deal_definition_id != target.id:
            raise InvalidDealTarget
    if supersedes is not None:
        if (
            target is not None
            and supersedes.target_deal_id is not None
            and supersedes.target_deal_id != target.id
        ):
            raise InvalidCorrectionLineage
        if (
            payload.target_prediction_id is not None
            and supersedes.target_prediction_id is not None
            and supersedes.target_prediction_id != payload.target_prediction_id
        ):
            raise InvalidCorrectionLineage
    try:
        with transaction.atomic():
            submission = Submission.objects.create(
                id=payload.submission_id,
                request_fingerprint=fingerprint,
                kind=Submission.Kind.DEAL_EVIDENCE,
                venue=venue,
                observed_at_client=payload.observed_at,
                received_at_server=received_at,
                time_quality=classify_time_quality(payload.observed_at, received_at),
                vantage_point=payload.vantage_point,
                client_platform=payload.client_platform,
                client_version=payload.client_version,
                entry_point=payload.entry_point,
            )
    except IntegrityError:
        raced = Submission.objects.filter(pk=payload.submission_id).first()
        if raced is None:
            raise
        return _receipt_for_existing(raced, payload, fingerprint)
    location = payload.location
    SubmissionPrivateContext.objects.create(
        submission=submission,
        actor=actor,
        account_id=account_id,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        location_accuracy_m=location.accuracy_meters if location else None,
        location_permission=location.permission if location else "not_supplied",
        network_verifier=network_verifier(remote_address),
    )
    DealEvidenceEvent.objects.create(
        submission=submission,
        action=payload.action,
        target_deal=target,
        target_prediction_id=payload.target_prediction_id,
        target_evidence=target_evidence,
        submitted_deal_shape=(
            payload.submitted_deal_shape.model_dump(mode="json", by_alias=True)
            if payload.submitted_deal_shape
            else None
        ),
        service_date_local=payload.service_date_local,
        target_local_datetime=payload.target_local_datetime,
        supersedes=supersedes,
    )
    return event_receipt(submission, duplicate=False)


def serialize_deal(deal: DealDefinition, *, prediction=None) -> dict:
    return {
        "id": deal.id,
        "canonical_family_id": deal.family_id,
        "latest_evidence_event_id": None,
        "display_name": public_deal_name(
            deal.display_name,
            price_kind=deal.price_kind,
            price_cents=deal.price_cents,
            price_low_cents=deal.price_low_cents,
            price_high_cents=deal.price_high_cents,
            discount_percent=deal.discount_percent,
        ),
        "category": deal.category,
        "price_kind": deal.price_kind,
        "price_cents": deal.price_cents,
        "price_low_cents": deal.price_low_cents,
        "price_high_cents": deal.price_high_cents,
        "discount_percent": float(deal.discount_percent)
        if deal.discount_percent is not None
        else None,
        "unit": deal.unit,
        "serving_format": deal.serving_format,
        "timing_description": deal.timing_description if deal.timing_known else None,
        "timing_known": deal.timing_known,
        "while_supplies_last": deal.while_supplies_last,
        "status": prediction.status if prediction is not None else deal.status,
        "prediction_id": prediction.id if prediction is not None else deal.prediction_id,
        # Materialization and definition creation are not user evidence. This
        # field becomes non-null only when admitted same-night evidence is
        # overlaid below.
        "latest_activity_at": None,
        # Server-only ordering metadata. It is removed after the same-night
        # evidence overlay and is not part of the public deal contract.
        "_prediction_rank": prediction.rank if prediction is not None else None,
    }


def _evidence_actor_key(event: DealEvidenceEvent) -> str | None:
    try:
        context = event.submission.private_context
    except SubmissionPrivateContext.DoesNotExist:
        return None
    if context.actor_id is not None:
        actor = context.actor
        if actor is None:
            return None
        try:
            linked_account_id = actor.account_link.account_id
        except ActorAccountLink.DoesNotExist:
            linked_account_id = None
        if linked_account_id is not None:
            # The durable link collapses guest and signed-in evidence from the
            # same installation. Its active-attribution flag affects trust and
            # submission attribution, not independence/abuse accounting.
            return f"account:{linked_account_id}"
    if context.account_id is not None:
        return f"account:{context.account_id}"
    if context.actor_id is not None:
        return f"actor:{context.actor_id}"
    return None


def _evidence_network_key(event: DealEvidenceEvent) -> str | None:
    try:
        verifier = event.submission.private_context.network_verifier
    except SubmissionPrivateContext.DoesNotExist:
        return None
    return verifier or None


def _shape_key(shape: dict) -> str:
    encoded = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _deal_from_shape(event: DealEvidenceEvent, shape: dict) -> dict:
    return {
        "id": event.id,
        "canonical_family_id": shape.get("canonicalFamilyId"),
        "latest_evidence_event_id": event.id,
        "display_name": public_deal_name(
            shape["displayName"],
            price_kind=shape["priceKind"],
            price_cents=shape.get("priceCents"),
            price_low_cents=shape.get("priceLowCents"),
            price_high_cents=shape.get("priceHighCents"),
            discount_percent=shape.get("discountPercent"),
        ),
        "category": shape["category"],
        "price_kind": shape["priceKind"],
        "price_cents": shape.get("priceCents"),
        "price_low_cents": shape.get("priceLowCents"),
        "price_high_cents": shape.get("priceHighCents"),
        "discount_percent": shape.get("discountPercent"),
        "unit": shape.get("unit", ""),
        "serving_format": shape.get("servingFormat", ""),
        "timing_description": (
            shape.get("timingDescription") if shape.get("timingKnown", False) else None
        ),
        "timing_known": shape.get("timingKnown", False),
        "while_supplies_last": shape.get("whileSuppliesLast", False),
        "status": "current",
        "prediction_id": None,
        "latest_activity_at": event.submission.observed_at_client,
        "_prediction_rank": None,
    }


def _public_shape(shape: dict, target_state: dict | None) -> dict | None:
    """Project preserved evidence into a public shape without publishing UGC text."""

    family = None
    family_id = shape.get("canonicalFamilyId")
    if family_id is not None:
        family = DealFamily.objects.filter(pk=family_id, category=shape["category"]).first()

    canonical_family_id: uuid.UUID | None
    if family is not None:
        canonical_family_id = family.id
        display_name = family.canonical_name
        category = family.category
    elif target_state is not None:
        canonical_family_id = target_state.get("canonical_family_id")
        display_name = target_state["display_name"]
        category = target_state["category"]
    else:
        # A custom or spoofed family is useful raw evidence, but there is no
        # server-curated label that is safe to return from a public endpoint.
        return None

    unit = ""
    serving_format = ""
    timing_description: str | None = None
    timing_known = False
    if target_state is not None and (
        family is None
        or str(target_state.get("canonical_family_id")) == str(canonical_family_id)
    ):
        if shape.get("unit", "") == target_state.get("unit", ""):
            unit = target_state.get("unit", "")
        if shape.get("servingFormat", "") == target_state.get("serving_format", ""):
            serving_format = target_state.get("serving_format", "")
        if (
            shape.get("timingKnown", False) == target_state.get("timing_known", False)
            and shape.get("timingDescription") == target_state.get("timing_description")
        ):
            timing_description = target_state.get("timing_description")
            timing_known = target_state.get("timing_known", False)

    while_supplies_last = shape.get("whileSuppliesLast", False)
    if while_supplies_last:
        # This is a constrained boolean claim, not user-authored copy.
        timing_known = True

    return {
        "canonicalFamilyId": canonical_family_id,
        "displayName": display_name,
        "category": category,
        "priceKind": shape["priceKind"],
        "priceCents": shape.get("priceCents"),
        "priceLowCents": shape.get("priceLowCents"),
        "priceHighCents": shape.get("priceHighCents"),
        "discountPercent": shape.get("discountPercent"),
        "unit": unit,
        "servingFormat": serving_format,
        "timingDescription": timing_description,
        "timingKnown": timing_known,
        "whileSuppliesLast": while_supplies_last,
    }


def resolve_deal_evidence(venue: Venue, service_date, deals: list[dict]) -> list[dict]:
    """Overlay admitted, independently corroborated evidence on a nightly slate.

    A single actor can preserve any valid observation, but cannot add, remove,
    or rewrite a public offer. Account and actor/network deduplication are
    evaluated per target without a permanent trust score.
    """

    minimum_support = settings.DEAL_PUBLIC_CORROBORATION_ACTORS
    states: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for deal in deals:
        identity = (
            f"prediction:{deal['prediction_id']}"
            if deal["prediction_id"] is not None
            else f"deal:{deal['id']}"
        )
        states[identity] = deal
        aliases[f"deal:{deal['id']}"] = identity
        if deal["prediction_id"] is not None:
            aliases[f"prediction:{deal['prediction_id']}"] = identity

    events = list(
        DealEvidenceEvent.objects.filter(
            submission__venue=venue,
            service_date_local=service_date,
            submission__time_quality=Submission.TimeQuality.PLAUSIBLE,
        )
        .select_related(
            "submission",
            "submission__private_context",
            "submission__private_context__actor__account_link",
            "target_deal",
            "target_evidence",
        )
        .order_by(
            "submission__observed_at_client",
            "submission__received_at_server",
            "id",
        )
    )
    superseded_ids = {event.supersedes_id for event in events if event.supersedes_id}
    votes: dict[str, dict[str, tuple[str, str | None]]] = defaultdict(dict)
    proposals: dict[str, tuple[DealEvidenceEvent, dict, str | None]] = {}
    latest_activity: dict[str, datetime] = {}

    def record_activity(identity: str, event: DealEvidenceEvent) -> None:
        observed_at = event.submission.observed_at_client
        previous = latest_activity.get(identity)
        if previous is None or observed_at > previous:
            latest_activity[identity] = observed_at

    def target_identity(event: DealEvidenceEvent) -> str | None:
        if event.target_prediction_id is not None:
            return aliases.get(f"prediction:{event.target_prediction_id}")
        if event.target_deal_id is not None:
            return aliases.get(f"deal:{event.target_deal_id}")
        if event.target_evidence_id is not None:
            return aliases.get(f"evidence:{event.target_evidence_id}")
        return None

    for event in events:
        target = target_identity(event)
        actor_key = _evidence_actor_key(event)
        network_key = _evidence_network_key(event)
        is_superseded = event.id in superseded_ids
        if event.action in {"ADD_MISSING", "CORRECT"} and event.submitted_deal_shape:
            shape = event.submitted_deal_shape
            prefix = "add" if event.action == "ADD_MISSING" else f"correct:{target}"
            proposal = f"proposal:{prefix}:{_shape_key(shape)}"
            proposals.setdefault(proposal, (event, shape, target))
            aliases[f"evidence:{event.id}"] = proposal
            record_activity(proposal, event)
            # A pending correction is still evidence activity on the visible
            # row it targets, even before independent corroboration makes the
            # proposed replacement public.
            if target is not None:
                record_activity(target, event)
            if actor_key is not None and not is_superseded:
                votes[proposal][actor_key] = ("support", network_key)
            continue
        if target is None:
            continue
        aliases[f"evidence:{event.id}"] = target
        record_activity(target, event)
        if actor_key is None or is_superseded:
            continue
        if event.action == "CONFIRM_PRESENT":
            votes[target][actor_key] = ("support", network_key)
        elif event.action == "DENY_PRESENT":
            votes[target][actor_key] = ("deny", network_key)

    for identity in list(states):
        actor_votes = votes.get(identity, {})
        denials = _independent_vote_count(actor_votes, "deny")
        confirmations = _independent_vote_count(actor_votes, "support")
        if denials >= minimum_support:
            states.pop(identity, None)
        elif confirmations >= minimum_support:
            last_confirmation = next(
                event
                for event in reversed(events)
                if target_identity(event) == identity
                and event.action == "CONFIRM_PRESENT"
                and event.id not in superseded_ids
            )
            states[identity] = {
                **states[identity],
                "status": "current",
                "latest_evidence_event_id": last_confirmation.id,
            }

    for proposal, (event, shape, target) in proposals.items():
        actor_votes = votes.get(proposal, {})
        support = _independent_vote_count(actor_votes, "support")
        denials = _independent_vote_count(actor_votes, "deny")
        if support < minimum_support or denials >= minimum_support:
            continue
        target_state = states.get(target) if target is not None else None
        public_shape = _public_shape(shape, target_state)
        if public_shape is None:
            continue
        if target is not None:
            states.pop(target, None)
        replacement = _deal_from_shape(event, public_shape)
        if target_state is not None:
            replacement["_prediction_rank"] = target_state.get("_prediction_rank")
        states[proposal] = replacement

    for identity, state in states.items():
        observed_activity = latest_activity.get(identity)
        state["_latest_evidence_at"] = observed_activity
        existing_activity = state.get("latest_activity_at")
        if observed_activity is not None and (
            existing_activity is None or observed_activity > existing_activity
        ):
            state["latest_activity_at"] = observed_activity

    def display_order(deal: dict) -> tuple:
        evidence_at = deal.get("_latest_evidence_at")
        prediction_rank = deal.get("_prediction_rank")
        return (
            evidence_at is None,
            -evidence_at.timestamp() if evidence_at is not None else 0,
            prediction_rank if prediction_rank is not None else float("inf"),
            deal["display_name"].casefold(),
            str(deal["id"]),
        )

    ordered = sorted(states.values(), key=display_order)
    return [
        {
            key: value
            for key, value in deal.items()
            if key not in {"_latest_evidence_at", "_prediction_rank"}
        }
        for deal in ordered
    ]


def _independent_vote_count(votes: dict[str, tuple[str, str | None]], action: str) -> int:
    """Require distinct actor/account identities and distinct supplied networks."""

    selected_networks: set[str] = set()
    count = 0
    for _actor_key, (vote, network_key) in sorted(votes.items()):
        if vote != action:
            continue
        if network_key is not None and network_key in selected_networks:
            continue
        count += 1
        if network_key is not None:
            selected_networks.add(network_key)
    return count
