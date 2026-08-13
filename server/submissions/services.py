import hashlib
import hmac
import json

from config.geo import distance_m
from covers.models import CoverDecision, CoverObservation
from covers.services import decision_for_observation, decision_for_submission, serialize_decision
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from identity.attribution import submission_account_id
from identity.models import Account, ActorAccountLink, InstallationActor
from venues.models import Venue
from vibes.models import VibeObservation

from submissions.models import Submission, SubmissionPrivateContext
from submissions.rate_limits import enforce_submission_limits
from submissions.schemas import CoverSubmissionSchema


class IdempotencyConflict(Exception):
    pass


class UnknownVenue(Exception):
    pass


class InvalidDisplayedDecision(Exception):
    pass


class InvalidInstallationActor(Exception):
    pass


def lock_submission_id(submission_id) -> None:
    """Serialize equal client UUIDs before limits and writes on PostgreSQL."""

    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [str(submission_id)])


def request_fingerprint(payload: CoverSubmissionSchema) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"accepted-submission-payload-v1:{canonical}".encode(),
        hashlib.sha256,
    ).hexdigest()


def erased_request_fingerprint(submission_id) -> str:
    """Replace exact-payload replay metadata once its private actor is erased."""

    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"erased-submission-v1:{submission_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def network_verifier(address: str | None) -> str:
    if not address:
        return ""
    pepper = getattr(settings, "NETWORK_METADATA_PEPPER", settings.SECRET_KEY)
    return hmac.new(pepper.encode(), address.encode(), hashlib.sha256).hexdigest()


def classify_time_quality(observed_at, received_at) -> str:
    future_tolerance = settings.CLIENT_CLOCK_FUTURE_TOLERANCE_SECONDS
    maximum_age = settings.CLIENT_INTERACTION_MAX_AGE_SECONDS
    difference = (observed_at - received_at).total_seconds()
    if difference > future_tolerance:
        return Submission.TimeQuality.FUTURE_SKEW
    if difference < -maximum_age:
        return Submission.TimeQuality.STALE_INTERACTION
    return Submission.TimeQuality.PLAUSIBLE


def actor_context_signals(actor, payload) -> tuple[bool, bool]:
    previous = (
        SubmissionPrivateContext.objects.filter(actor=actor)
        .select_related("submission")
        .order_by("-submission__observed_at_client")
        .first()
    )
    if previous is None:
        return False, False
    elapsed = (payload.observed_at - previous.submission.observed_at_client).total_seconds()
    rapid_spam = 0 <= elapsed < settings.RAPID_REPORT_WINDOW_SECONDS
    location = payload.location
    if location is None or previous.latitude is None or previous.longitude is None or elapsed <= 0:
        return False, rapid_spam
    traveled = distance_m(
        previous.latitude,
        previous.longitude,
        location.latitude,
        location.longitude,
    )
    return traveled / elapsed > settings.IMPOSSIBLE_MOVEMENT_SPEED_MPS, rapid_spam


def receipt_for(submission: Submission, *, duplicate: bool) -> dict:
    decision = decision_for_submission(submission)
    return {
        "submission_id": submission.id,
        "accepted_at": submission.received_at_server,
        "duplicate": duplicate,
        "cover": serialize_decision(decision, submission.received_at_server),
    }


def _receipt_for_existing(
    existing: Submission, payload: CoverSubmissionSchema, fingerprint: str
) -> dict:
    if existing.request_fingerprint != fingerprint or existing.kind != Submission.Kind.OBSERVATIONS:
        raise IdempotencyConflict
    return receipt_for(existing, duplicate=True)


@transaction.atomic
def accept_cover_submission(
    actor: InstallationActor,
    payload: CoverSubmissionSchema,
    *,
    remote_address: str | None,
    session_account: Account | None = None,
) -> dict:
    fingerprint = request_fingerprint(payload)
    lock_submission_id(payload.submission_id)
    existing = Submission.objects.filter(pk=payload.submission_id).first()
    if existing:
        return _receipt_for_existing(existing, payload, fingerprint)

    # Authentication happened before this transaction. Lock and revalidate so
    # actor deletion/rotation cannot pass its context-erasure snapshot while a
    # new private context is still being written.
    actor = lock_actor_lifecycle(actor.pk)
    account_id = submission_account_id(actor, session_account)

    venue = Venue.objects.filter(pk=payload.venue_id, is_active=True).first()
    if venue is None:
        raise UnknownVenue
    enforce_submission_limits(
        actor,
        account_id=account_id,
        venue_id=venue.id,
        remote_address=remote_address,
        now_seconds=int(timezone.now().timestamp()),
    )

    displayed_decision = None
    displayed_source = ""
    displayed_price_kind = ""
    displayed_price_cents = None
    displayed_price_low_cents = None
    displayed_price_high_cents = None
    if payload.cover and payload.cover.displayed_decision_id:
        displayed_decision = CoverDecision.objects.filter(
            pk=payload.cover.displayed_decision_id, venue=venue
        ).first()
        if displayed_decision is None:
            raise InvalidDisplayedDecision
        displayed_source = displayed_decision.source
        displayed_price_kind = displayed_decision.result_price_kind
        displayed_price_cents = displayed_decision.result_price_cents
        displayed_price_low_cents = displayed_decision.result_low_cents
        displayed_price_high_cents = displayed_decision.result_high_cents

    received_at = timezone.now()
    impossible_movement, rapid_spam = actor_context_signals(actor, payload)
    try:
        # The savepoint keeps the outer transaction usable after a concurrent
        # request wins the client-UUID insert.
        with transaction.atomic():
            submission = Submission.objects.create(
                id=payload.submission_id,
                request_fingerprint=fingerprint,
                kind=Submission.Kind.OBSERVATIONS,
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
    location_distance = None
    if location is not None and venue.latitude is not None and venue.longitude is not None:
        location_distance = distance_m(
            location.latitude,
            location.longitude,
            venue.latitude,
            venue.longitude,
        )
    evidence_snapshot = {
        "timeQuality": submission.time_quality,
        "signedIn": account_id is not None,
        "locationSupplied": location is not None,
        "distanceToVenueM": round(location_distance, 1) if location_distance is not None else None,
        "locationAccuracyM": location.accuracy_meters if location is not None else None,
        "installationAgeDays": max(0.0, (received_at - actor.created_at).total_seconds() / 86_400),
        "impossibleMovement": impossible_movement,
        "rapidSpam": rapid_spam,
        "resolverVersion": "cover_trust_v1",
    }
    SubmissionPrivateContext.objects.create(
        submission=submission,
        actor=actor,
        account_id=account_id,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        location_accuracy_m=location.accuracy_meters if location else None,
        location_permission=location.permission if location else "not_supplied",
        network_verifier=network_verifier(remote_address),
        evidence_snapshot=evidence_snapshot,
    )
    if payload.cover:
        cover = payload.cover
        observation = CoverObservation.objects.create(
            submission=submission,
            independence_group_key=actor.id,
            reported_price_cents=cover.price_cents,
            interaction_kind=cover.interaction,
            displayed_decision=displayed_decision,
            displayed_source=displayed_source,
            displayed_price_kind=displayed_price_kind,
            displayed_price_cents=displayed_price_cents,
            displayed_price_low_cents=displayed_price_low_cents,
            displayed_price_high_cents=displayed_price_high_cents,
            price_prefilled=cover.price_prefilled,
            price_touched=cover.price_touched,
            admission_snapshot=evidence_snapshot,
        )
        decision_for_observation(observation)
    VibeObservation.objects.bulk_create(
        [
            VibeObservation(submission=submission, dimension=vibe.dimension, value=vibe.value)
            for vibe in payload.vibes
        ]
    )
    return receipt_for(submission, duplicate=False)


def lock_actor_lifecycle(actor_id) -> InstallationActor:
    """Lock linked account before actor, revalidating both lifecycle rows."""

    account_id = (
        ActorAccountLink.objects.filter(actor_id=actor_id)
        .values_list("account_id", flat=True)
        .first()
    )
    if account_id is not None:
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            raise InvalidInstallationActor
    actor = InstallationActor.objects.select_for_update().filter(pk=actor_id).first()
    if actor is None:
        raise InvalidInstallationActor
    if (
        account_id is not None
        and not ActorAccountLink.objects.filter(actor=actor, account_id=account_id).exists()
    ):
        raise InvalidInstallationActor
    if account_id is None and ActorAccountLink.objects.filter(actor=actor).exists():
        # A link committed while this request waited for the actor row. Retry
        # from the public endpoint so the next transaction takes the required
        # account -> actor lock order instead of writing account-linked context
        # without holding the account lifecycle lock.
        raise InvalidInstallationActor
    return actor
