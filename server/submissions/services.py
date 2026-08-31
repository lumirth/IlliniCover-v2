from decimal import ROUND_HALF_UP, Decimal

from config.geo import distance_m
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from identity.attribution import submission_account_id
from product.models import Account, InstallationActor, Submission, SubmissionPrivateContext, Venue

from submissions.rate_limits import enforce_submission_limits


class IdempotencyConflict(Exception):
    pass


class UnknownVenue(Exception):
    pass


class InvalidInstallationActor(Exception):
    pass


def classify_time(observed_at, received_at):
    age = (observed_at - received_at).total_seconds()
    if age > settings.CLIENT_CLOCK_FUTURE_TOLERANCE_SECONDS:
        return "future_skew"
    if age < -settings.CLIENT_INTERACTION_MAX_AGE_SECONDS:
        return "stale_interaction"
    return "plausible"


def actor_signals(actor, payload):
    previous = (
        SubmissionPrivateContext.objects.filter(actor=actor)
        .select_related("submission")
        .order_by("-submission__observed_at_client")
        .first()
    )
    if previous is None:
        return False, False
    elapsed = (payload.observed_at - previous.submission.observed_at_client).total_seconds()
    rapid = 0 <= elapsed < settings.RAPID_REPORT_WINDOW_SECONDS
    location = payload.location
    if not location or previous.latitude is None or elapsed <= 0:
        return False, rapid
    traveled = distance_m(
        previous.latitude, previous.longitude, location.latitude, location.longitude
    )
    return traveled / elapsed > settings.IMPOSSIBLE_MOVEMENT_SPEED_MPS, rapid


def submission_trust(actor, payload, venue, received, *, signed_in):
    impossible, rapid = actor_signals(actor, payload)
    location, signal = payload.location, "neutral"
    if location and venue.latitude is not None and location.accuracy_meters <= 100:
        distance = distance_m(
            location.latitude, location.longitude, venue.latitude, venue.longitude
        )
        signal = "nearby" if distance <= 250 else ("far" if distance >= 5_000 else "neutral")
    return classify_time(payload.observed_at, received), {
        "signedIn": signed_in,
        "locationSignal": signal,
        "impossibleMovement": impossible,
        "rapidSpam": rapid,
    }


def receipt_for(submission, *, duplicate):
    from covers.services import decision_for_submission, serialize_decision

    decision = decision_for_submission(submission)
    return {
        "submission_id": submission.pk,
        "accepted_at": submission.received_at_server,
        "duplicate": duplicate,
        "cover": serialize_decision(decision, submission.received_at_server),
    }


def location_values(location):
    if location is None:
        return None, None, None, "not_supplied"
    latitude = Decimal(str(location.latitude)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    longitude = Decimal(str(location.longitude)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    accuracy = Decimal(str(location.accuracy_meters)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return latitude, longitude, accuracy, location.permission or "when_in_use"


def same_location(existing, location):
    context = SubmissionPrivateContext.objects.filter(submission=existing).first()
    if context is None:
        return True
    latitude, longitude, accuracy, permission = location_values(location)
    return bool(
        context.latitude == latitude
        and context.longitude == longitude
        and context.location_accuracy_m == accuracy
        and context.location_permission == permission
    )


def existing_cover_receipt(existing, payload):
    cover = payload.cover.model_dump(mode="json", by_alias=True) if payload.cover else {}
    vibes = [vibe.model_dump(mode="json") for vibe in payload.vibes]
    if not (
        existing.kind == Submission.Kind.OBSERVATIONS
        and existing.venue_id == payload.venue_id
        and existing.observed_at_client == payload.observed_at
        and existing.vantage_point == payload.vantage_point
        and existing.client_platform == payload.client_platform
        and existing.entry_point == payload.entry_point
        and existing.cover_echo == cover
        and existing.vibes == vibes
        and same_location(existing, payload.location)
    ):
        raise IdempotencyConflict
    return receipt_for(existing, duplicate=True)


def lock_submission_identity(actor, session_account):
    account_ids = {
        account_id
        for account_id in (
            actor.account_id,
            session_account.pk if session_account is not None else None,
        )
        if account_id is not None
    }
    accounts = {
        account.pk: account
        for account in Account.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("pk")
    }
    if len(accounts) != len(account_ids):
        raise InvalidInstallationActor
    actor = InstallationActor.objects.select_for_update().filter(pk=actor.pk).first()
    if actor is None or (actor.account_id is not None and actor.account_id not in accounts):
        raise InvalidInstallationActor
    locked_session = accounts[session_account.pk] if session_account is not None else None
    return actor, locked_session


@transaction.atomic
def accept_cover_submission(
    actor: InstallationActor,
    payload,
    *,
    remote_address: str | None,
    session_account: Account | None = None,
):
    existing = Submission.objects.filter(pk=payload.submission_id).first()
    if existing:
        return existing_cover_receipt(existing, payload)
    actor, session_account = lock_submission_identity(actor, session_account)
    account_id = submission_account_id(actor, session_account)
    venue = Venue.objects.filter(pk=payload.venue_id, is_active=True).first()
    if venue is None:
        raise UnknownVenue
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
                kind=Submission.Kind.OBSERVATIONS,
                venue=venue,
                observed_at_client=payload.observed_at,
                received_at_server=received,
                time_quality=time_quality,
                vantage_point=payload.vantage_point,
                client_platform=payload.client_platform,
                entry_point=payload.entry_point,
                independence_group=account_id or actor.pk,
                cover_price_cents=payload.cover.price_cents if payload.cover else None,
                cover_interaction=payload.cover.interaction if payload.cover else "",
                cover_echo=(
                    payload.cover.model_dump(mode="json", by_alias=True) if payload.cover else {}
                ),
                vibes=[vibe.model_dump(mode="json") for vibe in payload.vibes],
                trust=trust,
            )
    except IntegrityError:
        return existing_cover_receipt(Submission.objects.get(pk=payload.submission_id), payload)
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
    return receipt_for(submission, duplicate=False)
