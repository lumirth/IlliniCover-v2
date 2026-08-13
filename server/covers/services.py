import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config.geo import distance_m
from context.models import AdvertisedAdmission, SourceFetch
from django.conf import settings
from django.db.models import Max, Prefetch, Q
from django.utils import timezone
from submissions.models import Submission, SubmissionPrivateContext
from venues.models import Venue
from vibes.models import VibeObservation

from covers.modeling import (
    AdmissionClass,
    AdvertisedAdmissionInput,
    HistoricalModel,
    HistoricalModelConfig,
    HistoricalObservation,
    LocationContext,
    ObservationInput,
    assess_observation,
    compute_nowcast,
    cover_at,
    resolve_cover,
)
from covers.models import CoverDecision, CoverModelRelease, CoverObservation

CHICAGO = ZoneInfo("America/Chicago")
SERVICE_NIGHT_CUTOFF_HOUR = 5
FREE_HISTORY_SERVICE_NIGHTS = 7
PREMIUM_HISTORY_SERVICE_NIGHTS = 90
FREE_HISTORY_REPORT_LIMIT = 50
PREMIUM_HISTORY_REPORT_LIMIT = 250


def current_time() -> datetime:
    if getattr(settings, "VISUAL_ACCEPTANCE", False):
        fixed = getattr(settings, "VISUAL_ACCEPTANCE_NOW", None)
        if fixed is not None:
            return fixed
    return timezone.now()


def generation_time(moment: datetime | None = None) -> datetime:
    if moment is None:
        moment = current_time()
    return moment.replace(second=(moment.second // 15) * 15, microsecond=0)


def authoritative_release_at(knowledge_cutoff: datetime) -> CoverModelRelease | None:
    """Return the release that was actually available by the stated cutoff."""

    return (
        CoverModelRelease.objects.filter(
            Q(
                promoted_at__lte=knowledge_cutoff,
            )
            & (Q(retired_at__isnull=True) | Q(retired_at__gt=knowledge_cutoff))
            | Q(
                promoted_at__isnull=True,
                created_at__lte=knowledge_cutoff,
                is_authoritative=True,
            )
            | Q(
                promoted_at__isnull=True,
                created_at__lte=knowledge_cutoff,
                retired_at__gt=knowledge_cutoff,
                model_kind="historical",
            )
        )
        .order_by("-promoted_at", "-created_at")
        .first()
    )


def service_date_for(moment: datetime):
    local = moment.astimezone(CHICAGO)
    if local.hour < SERVICE_NIGHT_CUTOFF_HOUR:
        local -= timedelta(days=1)
    return local.date()


def service_night_bounds(moment: datetime) -> tuple[datetime, datetime]:
    service_date = service_date_for(moment)
    start = datetime.combine(service_date, datetime.min.time(), tzinfo=CHICAGO) + timedelta(
        hours=SERVICE_NIGHT_CUTOFF_HOUR
    )
    return start, start + timedelta(days=1)


def decision_for_observation(observation: CoverObservation) -> CoverDecision | None:
    submission = observation.submission
    age_seconds = (submission.received_at_server - submission.observed_at_client).total_seconds()
    if (
        submission.time_quality != Submission.TimeQuality.PLAUSIBLE
        or age_seconds > settings.COVER_LIVE_HORIZON_SECONDS
    ):
        return None
    resolution = resolve_at(
        observation.submission.venue,
        observation.submission.received_at_server,
        observation.submission.received_at_server,
    )
    if resolution.source in {"unavailable", "historical"}:
        return None
    return persist_resolution(
        submission.venue,
        submission.received_at_server,
        submission.received_at_server,
        resolution,
        evidence_revision=f"submission:{submission.id}:{resolution.receipt_sha256()[:16]}",
    )


def _model_inputs(knowledge_cutoff: datetime) -> tuple[HistoricalModel, list[ObservationInput]]:
    historical_rows: list[HistoricalObservation] = []
    live_rows: list[ObservationInput] = []
    observations = (
        CoverObservation.objects.filter(submission__received_at_server__lte=knowledge_cutoff)
        .select_related("submission", "submission__private_context", "submission__venue")
        .order_by("submission__received_at_server", "submission_id")
    )
    for observation in observations:
        submission = observation.submission
        if submission.source_kind == "dataset_import":
            historical_rows.append(
                HistoricalObservation(
                    observation_id=str(submission.id),
                    venue_id=str(submission.venue_id),
                    observed_at=submission.observed_at_client,
                    available_at=submission.received_at_server,
                    service_date=service_date_for(submission.observed_at_client),
                    price_cents=observation.reported_price_cents,
                )
            )
            continue
        live_rows.append(observation_input(observation))
    release = authoritative_release_at(knowledge_cutoff)
    if release and release.parameters_or_artifact.get("artifact_schema"):
        model = HistoricalModel.from_artifact(release.parameters_or_artifact)
    else:
        model = HistoricalModel.fit(
            historical_rows,
            HistoricalModelConfig(release_id="cover_historical_v1"),
        )
    return model, live_rows


def observation_input(observation: CoverObservation) -> ObservationInput:
    """Rehydrate the immutable evidence assessment input for serving or training."""

    submission = observation.submission
    try:
        context = submission.private_context
    except SubmissionPrivateContext.DoesNotExist:
        context = None
    snapshot = observation.admission_snapshot
    installation_age_days = snapshot.get("installationAgeDays")
    if context is not None and context.actor is not None:
        installation_age_days = max(
            0.0,
            (submission.received_at_server - context.actor.created_at).total_seconds() / 86_400,
        )
    return ObservationInput(
        observation_id=str(submission.id),
        venue_id=str(submission.venue_id),
        actor_independence_key=str(observation.independence_group_key),
        observed_at=submission.observed_at_client,
        received_at=submission.received_at_server,
        price_cents=observation.reported_price_cents,
        interaction_kind=observation.interaction_kind,
        displayed_source=observation.displayed_source or None,
        displayed_price_cents=observation.displayed_price_cents,
        price_prefilled=observation.price_prefilled,
        price_touched=observation.price_touched,
        time_quality=(
            "good"
            if submission.time_quality == Submission.TimeQuality.PLAUSIBLE
            else submission.time_quality
        ),
        location=_location_context(submission.venue, context, observation),
        installation_age_days=installation_age_days,
        prior_corroborations=int(snapshot.get("priorCorroborations", 0)),
        signed_in=(context is not None and context.account_id is not None)
        or bool(snapshot.get("signedIn", False)),
        hard_abuse=bool(snapshot.get("hardAbuse", False)),
        impossible_movement=bool(snapshot.get("impossibleMovement", False)),
        rapid_spam=bool(snapshot.get("rapidSpam", False)),
        linked_account_stuffing=bool(snapshot.get("linkedAccountStuffing", False)),
        known_automation=bool(snapshot.get("knownAutomation", False)),
        severe_clock_manipulation=bool(snapshot.get("severeClockManipulation", False)),
    )


def _location_context(
    venue: Venue,
    context: SubmissionPrivateContext | None,
    observation: CoverObservation | None = None,
):
    if (
        context is None
        or context.latitude is None
        or context.longitude is None
        or context.location_accuracy_m is None
        or venue.latitude is None
        or venue.longitude is None
    ):
        snapshot = observation.admission_snapshot if observation is not None else {}
        distance = snapshot.get("distanceToVenueM")
        accuracy = snapshot.get("locationAccuracyM")
        if distance is None or accuracy is None:
            return None
        return LocationContext(distance_to_venue_m=float(distance), accuracy_m=float(accuracy))
    return LocationContext(
        distance_to_venue_m=distance_m(
            context.latitude,
            context.longitude,
            venue.latitude,
            venue.longitude,
        ),
        accuracy_m=float(context.location_accuracy_m),
    )


def resolve_at(venue: Venue, target_time: datetime, knowledge_cutoff: datetime):
    model, live_rows = _model_inputs(knowledge_cutoff)
    prediction = model.predict(str(venue.id), target_time, knowledge_cutoff)
    nowcast = compute_nowcast(
        target_venue_id=str(venue.id),
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        observations=live_rows,
        historical_lookup=model.predict,
    )
    return resolve_cover(
        venue_id=str(venue.id),
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        observations=live_rows,
        advertised_admissions=_advertised_admission_inputs(venue, target_time, knowledge_cutoff),
        historical_prediction=prediction,
        nowcast=nowcast,
        live_horizon_seconds=settings.COVER_LIVE_HORIZON_SECONDS,
    )


def _advertised_admission_inputs(
    venue: Venue, target_time: datetime, knowledge_cutoff: datetime | None = None
) -> tuple[AdvertisedAdmissionInput, ...]:
    """Translate only current validated universal facts into resolver inputs."""

    knowledge_cutoff = knowledge_cutoff or target_time
    facts = (
        AdvertisedAdmission.objects.filter(
            venue=venue,
            is_unconditional=True,
            qualification="",
            starts_at__lte=target_time,
            source_fetch__fetched_at__lte=knowledge_cutoff,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=target_time))
        .select_related("source_fetch")
    )
    return tuple(
        AdvertisedAdmissionInput(
            admission_id=str(fact.id),
            venue_id=str(fact.venue_id),
            price_cents=fact.price_cents,
            available_at=fact.source_fetch.fetched_at,
            starts_at=fact.starts_at,
            ends_at=fact.ends_at,
            is_unconditional=fact.is_unconditional,
            qualification=fact.qualification,
        )
        for fact in facts.order_by("price_cents", "id")
    )


def reconstruct_at(venue: Venue, target_time: datetime, knowledge_cutoff: datetime):
    model, live_rows = _model_inputs(knowledge_cutoff)
    return cover_at(
        venue_id=str(venue.id),
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        observations=live_rows,
        advertised_admissions=_advertised_admission_inputs(venue, target_time, knowledge_cutoff),
        historical_model=model,
        live_horizon_seconds=settings.COVER_LIVE_HORIZON_SECONDS,
    )


def persist_resolution(
    venue: Venue,
    target_time: datetime,
    knowledge_cutoff: datetime,
    resolution,
    *,
    evidence_revision: str | None = None,
    served_state_key: str | None = None,
) -> CoverDecision:
    release = authoritative_release_at(knowledge_cutoff)
    revision = evidence_revision or f"resolution:{resolution.receipt_sha256()}"
    values = {
        "venue": venue,
        "target_time": target_time,
        "knowledge_cutoff": knowledge_cutoff,
        "result_price_kind": resolution.price_kind,
        "result_price_cents": resolution.amount_cents,
        "result_low_cents": resolution.low_cents,
        "result_high_cents": resolution.high_cents,
        "source": resolution.source,
        "status": resolution.status,
        "model_release": release,
        "evidence_revision": revision,
        "resolver_version": "cover_resolver_v1",
        "same_night_adjustment_summary": {
            "support": round(resolution.support, 6),
            "evidenceIds": list(resolution.evidence_ids),
            "reasons": list(resolution.reasons),
            "freshnessSeconds": resolution.freshness_seconds,
            "receiptSha256": resolution.receipt_sha256(),
            "venueAdjustmentCents": resolution.venue_adjustment_cents,
        },
        "campus_adjustment_summary": {
            "campusAdjustmentCents": resolution.campus_adjustment_cents,
        },
    }
    if served_state_key is not None:
        exact = CoverDecision.objects.filter(
            venue=venue,
            target_time=target_time,
            knowledge_cutoff=knowledge_cutoff,
            evidence_revision=revision,
        ).first()
        if exact is not None:
            return exact
        decision, _created = CoverDecision.objects.get_or_create(
            served_state_key=served_state_key,
            defaults=values,
        )
        return decision
    decision, _created = CoverDecision.objects.get_or_create(
        venue=venue,
        target_time=target_time,
        knowledge_cutoff=knowledge_cutoff,
        evidence_revision=revision,
        defaults={
            key: value
            for key, value in values.items()
            if key not in {"venue", "target_time", "knowledge_cutoff", "evidence_revision"}
        },
    )
    return decision


def serve_resolution(venue: Venue, target_time: datetime, knowledge_cutoff: datetime):
    resolution = resolve_at(venue, target_time, knowledge_cutoff)
    return persist_resolution(
        venue,
        target_time,
        knowledge_cutoff,
        resolution,
        served_state_key=served_resolution_state_key(venue, target_time, resolution),
    )


def served_resolution_state_key(venue: Venue, target_time: datetime, resolution) -> str:
    """Identify one reusable served state without making elapsed time a write cadence."""

    summary = resolution.receipt_summary()
    stable_state = {
        "schema": "cover_served_state_v1",
        "venueId": str(venue.id),
        "serviceDate": service_date_for(target_time).isoformat(),
        "priceKind": summary["price_kind"],
        "amountCents": summary["amount_cents"],
        "lowCents": summary["low_cents"],
        "highCents": summary["high_cents"],
        "source": summary["source"],
        "status": summary["status"],
        "reasons": summary["reasons"],
        "evidenceIds": summary["evidence_ids"],
        "modelRelease": summary["model_release"],
        "venueAdjustmentCents": summary["venue_adjustment_cents"],
        "campusAdjustmentCents": summary["campus_adjustment_cents"],
    }
    encoded = json.dumps(stable_state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def decision_for_submission(submission: Submission) -> CoverDecision | None:
    return CoverDecision.objects.filter(
        evidence_revision__startswith=f"submission:{submission.id}:"
    ).first()


def serialize_venue(venue: Venue) -> dict:
    return {
        "id": venue.id,
        "slug": venue.slug,
        "name": venue.name,
        "address": venue.address,
        "opened_year": venue.opened_year,
    }


def serialize_decision(decision: CoverDecision | None, now: datetime) -> dict | None:
    if decision is None:
        return None
    price = {
        "kind": decision.result_price_kind,
        "amount_cents": decision.result_price_cents,
        "low_cents": decision.result_low_cents,
        "high_cents": decision.result_high_cents,
    }
    stored_freshness = decision.same_night_adjustment_summary.get("freshnessSeconds")
    if stored_freshness is None:
        freshness_seconds = 0
    else:
        freshness_seconds = int(stored_freshness) + max(
            0, int((now - decision.knowledge_cutoff).total_seconds())
        )
    return {
        "price": price,
        "source": decision.source,
        "freshness_seconds": freshness_seconds,
        "decision_id": decision.id,
        "status": decision.status,
    }


def current_decision(venue: Venue, now: datetime) -> CoverDecision | None:
    horizon_start = now - timedelta(seconds=settings.COVER_LIVE_HORIZON_SECONDS)
    return venue.cover_decisions.filter(
        target_time__gte=horizon_start,
        target_time__lte=now,
        evidence_revision__startswith="submission:",
    ).first()


def current_vibes(venue: Venue, *, now: datetime | None = None) -> dict[str, str | None]:
    now = now or timezone.now()
    values: dict[str, str | None] = {
        "line_length": None,
        "line_speed": None,
        "crowd_level": None,
    }
    observations = (
        VibeObservation.objects.filter(
            submission__venue=venue,
            submission__time_quality=Submission.TimeQuality.PLAUSIBLE,
            submission__observed_at_client__lte=now,
        )
        .select_related(
            "submission",
            "submission__private_context",
            "submission__cover_observation",
            "submission__venue",
        )
        .order_by("-submission__observed_at_client")
    )
    for observation in observations:
        try:
            private_context = observation.submission.private_context
        except SubmissionPrivateContext.DoesNotExist:
            private_context = None
        if private_context is not None:
            snapshot = private_context.evidence_snapshot
            if snapshot.get("impossibleMovement", False) or snapshot.get("rapidSpam", False):
                continue
        cover_observation = getattr(observation.submission, "cover_observation", None)
        if cover_observation is not None:
            assessment = assess_observation(
                observation_input(cover_observation), knowledge_cutoff=now
            )
            if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
                continue
        age_seconds = (now - observation.submission.observed_at_client).total_seconds()
        if (
            values[observation.dimension] is None
            and age_seconds <= settings.VIBE_FRESHNESS_SECONDS[observation.dimension]
        ):
            values[observation.dimension] = observation.value
        if all(value is not None for value in values.values()):
            break
    return values


def recent_reports(
    venue: Venue,
    *,
    moment: datetime | None = None,
    limit: int = 50,
    window_start: datetime | None = None,
) -> list[dict]:
    moment = moment or timezone.now()
    start, end = service_night_bounds(moment)
    start = window_start or start
    submissions = (
        Submission.objects.filter(
            venue=venue,
            kind=Submission.Kind.OBSERVATIONS,
            observed_at_client__gte=start,
            observed_at_client__lt=end,
            observed_at_client__lte=moment,
        )
        .filter(Q(cover_observation__isnull=False) | Q(vibe_observations__isnull=False))
        .select_related(
            "private_context",
            "private_context__actor",
            "cover_observation",
            "venue",
        )
        .prefetch_related(Prefetch("vibe_observations"))
        .distinct()
        .order_by("-observed_at_client", "-received_at_server")
    )
    reports = []
    for submission in submissions:
        try:
            observation = submission.cover_observation
        except CoverObservation.DoesNotExist:
            observation = None
        if observation is not None:
            assessment = assess_observation(observation_input(observation), knowledge_cutoff=moment)
            if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
                continue
        else:
            if submission.time_quality != Submission.TimeQuality.PLAUSIBLE:
                continue
            try:
                snapshot = submission.private_context.evidence_snapshot
            except SubmissionPrivateContext.DoesNotExist:
                snapshot = {}
            if snapshot.get("impossibleMovement", False) or snapshot.get("rapidSpam", False):
                continue
        broad_context = {
            Submission.VantagePoint.OUTSIDE.value: "Outside",
            Submission.VantagePoint.INSIDE.value: "Inside",
        }.get(submission.vantage_point)
        reports.append(
            {
                "submission_id": submission.id,
                "observed_at": submission.observed_at_client,
                "received_at": submission.received_at_server,
                "price_cents": (
                    observation.reported_price_cents if observation is not None else None
                ),
                "interaction": observation.interaction_kind if observation is not None else "vibes",
                "broad_context": broad_context,
                "vibes": [
                    f"{vibe.dimension}:{vibe.value}" for vibe in submission.vibe_observations.all()
                ],
            }
        )
        if len(reports) >= limit:
            break
    return reports


def report_history(venue: Venue, *, moment: datetime, premium: bool) -> dict:
    """Return the bounded public report timeline for the caller's access tier.

    The current service night counts as the first night. Report contents remain
    admission-filtered and privacy-minimized by ``recent_reports``; premium
    changes only how far back the public timeline reaches and its result cap.
    """

    current_start, _ = service_night_bounds(moment)
    service_nights = PREMIUM_HISTORY_SERVICE_NIGHTS if premium else FREE_HISTORY_SERVICE_NIGHTS
    report_limit = PREMIUM_HISTORY_REPORT_LIMIT if premium else FREE_HISTORY_REPORT_LIMIT
    window_start = current_start - timedelta(days=service_nights - 1)
    reports = recent_reports(
        venue,
        moment=moment,
        limit=report_limit + 1,
        window_start=window_start,
    )
    return {
        "access_tier": "extended" if premium else "limited",
        "window_start": window_start,
        "has_more": len(reports) > report_limit,
        "reports": reports[:report_limit],
    }


def public_cover_observations(venue: Venue, *, moment: datetime) -> list[CoverObservation]:
    """Return the one admission-filtered source for public timeline and count."""

    start, end = service_night_bounds(moment)
    observations = (
        CoverObservation.objects.filter(
            submission__venue=venue,
            submission__observed_at_client__gte=start,
            submission__observed_at_client__lt=end,
            submission__observed_at_client__lte=moment,
        )
        .select_related(
            "submission",
            "submission__private_context",
            "submission__private_context__actor",
            "submission__venue",
        )
        .prefetch_related(Prefetch("submission__vibe_observations"))
        .order_by("-submission__observed_at_client")
    )
    admitted = []
    for observation in observations:
        assessment = assess_observation(observation_input(observation), knowledge_cutoff=moment)
        if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
            continue
        admitted.append(observation)
    return admitted


def latest_public_activity_at(venue: Venue, *, moment: datetime) -> datetime | None:
    """Return the latest admitted public cover or vibe activity for v1-parity sorting."""

    latest = None
    for report in recent_reports(venue, moment=moment):
        observed_at = report["observed_at"]
        if latest is None or observed_at > latest:
            latest = observed_at
    advertised = (
        AdvertisedAdmission.objects.filter(
            venue=venue,
            is_unconditional=True,
            qualification="",
            starts_at__lte=moment,
            source_fetch__fetched_at__lte=moment,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=moment))
        .aggregate(latest=Max("source_fetch__fetched_at"))["latest"]
    )
    if advertised is not None and (latest is None or advertised > latest):
        latest = advertised
    model_release = authoritative_release_at(moment)
    model_updated = (
        model_release.promoted_at or model_release.created_at if model_release is not None else None
    )
    if model_updated is not None and (latest is None or model_updated > latest):
        latest = model_updated
    return latest


def cover_board(*, now: datetime | None = None) -> dict:
    now = now or current_time()
    generated_at = current_generation_cutoff(now)
    venues = list(Venue.objects.filter(is_active=True))
    cards = []
    for venue in venues:
        decision = serve_resolution(venue, generated_at, generated_at)
        report_count = len(public_cover_observations(venue, moment=now))
        cards.append(
            {
                "venue": serialize_venue(venue),
                "cover": serialize_decision(decision, generated_at),
                "recent_report_count": report_count,
                "latest_activity_at": latest_public_activity_at(venue, moment=now),
                "vibes": current_vibes(venue, now=now),
            }
        )
    return {
        "service_date": service_date_for(now),
        "generated_at": generated_at,
        "server_revision": getattr(settings, "CODE_REVISION", "development"),
        "venues": cards,
    }


def current_generation_cutoff(now: datetime) -> datetime:
    """Keep a representation stable for 15s unless a relevant input arrives."""

    bucket = generation_time(now)
    latest_observation = Submission.objects.filter(
        kind=Submission.Kind.OBSERVATIONS,
        received_at_server__gt=bucket,
        received_at_server__lte=now,
    ).aggregate(latest=Max("received_at_server"))["latest"]
    latest_source_fetch = SourceFetch.objects.filter(
        advertised_admissions__isnull=False,
        created_at__lte=now,
    ).aggregate(latest=Max("created_at"))["latest"]
    model_release = authoritative_release_at(now)
    latest_model_release = (
        model_release.promoted_at or model_release.created_at if model_release is not None else None
    )
    return max(
        candidate
        for candidate in (
            bucket,
            latest_observation,
            latest_source_fetch,
            latest_model_release,
        )
        if candidate is not None
    )
