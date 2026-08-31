import uuid
from datetime import datetime, timedelta

from billing.entitlements import account_has_premium
from config.network import client_address
from config.schemas import ErrorSchema
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from identity.auth import session_auth
from ninja import Header, Query, Router, Status
from product.models import Venue
from submissions.rate_limits import consume_rate_limit

from covers.schemas import (
    CoverBoardSchema,
    CoverHistorySchema,
    TimeMachineSchema,
    VenueCoverDetailSchema,
)
from covers.services import (
    cover_board,
    current_generation_cutoff,
    current_time,
    current_vibes,
    recent_reports,
    report_history,
    serialize_decision,
    serialize_venue,
    serve_resolution,
    service_date_for,
)
from covers.time_machine import normalize_time_machine_target

router = Router(tags=["Cover"])


def find_venue(value):
    query = Q(slug=value)
    try:
        query |= Q(pk=uuid.UUID(value))
    except ValueError:
        pass
    return Venue.objects.filter(query, is_active=True).first()


def error(request, status, code, message):
    return Status(status, {"code": code, "message": message, "request_id": request.request_id})


@router.get("/cover", response=CoverBoardSchema, operation_id="getCoverBoard", by_alias=True)
def get_cover_board(request):
    return cover_board()


@router.get(
    "/venues/{venue}/cover",
    response={200: VenueCoverDetailSchema, 404: ErrorSchema},
    operation_id="getVenueCover",
    by_alias=True,
)
def get_venue_cover(request, venue: str):
    selected = find_venue(venue)
    if selected is None:
        return error(request, 404, "venue_not_found", "That venue was not found.")
    from deals.api import venue_deals

    now = current_time()
    cutoff = current_generation_cutoff(now)
    return {
        "venue": serialize_venue(selected),
        "cover": serialize_decision(serve_resolution(selected, cutoff, cutoff), cutoff, cutoff),
        "recent_reports": recent_reports(selected, moment=now),
        "vibes": current_vibes(selected, now=now),
        "deals": venue_deals(selected, service_date_for(cutoff))["deals"],
    }


@router.get(
    "/venues/{venue}/cover/history",
    response={200: CoverHistorySchema, 404: ErrorSchema},
    operation_id="getVenueCoverHistory",
    by_alias=True,
)
def get_venue_cover_history(
    request, venue: str, x_session_token: str | None = Header(None, alias="X-Session-Token")
):
    selected = find_venue(venue)
    if selected is None:
        return error(request, 404, "venue_not_found", "That venue was not found.")
    now = current_time()
    account = session_auth.authenticate(request, x_session_token) if x_session_token else None
    return {
        "venue": serialize_venue(selected),
        "service_date": service_date_for(now),
        **report_history(
            selected, moment=now, premium=bool(account and account_has_premium(account))
        ),
    }


@router.get(
    "/venues/{venue}/cover/time-machine",
    auth=session_auth,
    response={
        200: TimeMachineSchema,
        401: ErrorSchema,
        403: ErrorSchema,
        404: ErrorSchema,
        422: ErrorSchema,
        429: ErrorSchema,
    },
    operation_id="getVenueCoverTimeMachine",
    by_alias=True,
)
def get_venue_time_machine(
    request,
    venue: str,
    target_time: datetime = Query(..., alias="targetTime"),  # noqa: B008
):
    selected = find_venue(venue)
    if selected is None:
        return error(request, 404, "venue_not_found", "That venue was not found.")
    if not account_has_premium(request.auth):
        return error(request, 403, "premium_required", "IlliniCover Blue is required.")
    if timezone.is_naive(target_time):
        return error(request, 422, "timezone_required", "target_time must include an offset.")
    now = current_time()
    if (
        not now - timedelta(days=settings.TIME_MACHINE_MAX_PAST_DAYS)
        <= target_time
        <= now + timedelta(days=settings.TIME_MACHINE_MAX_FUTURE_DAYS)
    ):
        return error(
            request, 422, "unsupported_target_time", "That target is outside the supported window."
        )
    account_limit, account_window = settings.TIME_MACHINE_ACCOUNT_RATE_LIMIT
    network_limit, network_window = settings.TIME_MACHINE_NETWORK_RATE_LIMIT
    second = int(now.timestamp())
    allowed = consume_rate_limit(
        "time-machine-account",
        request.auth.pk,
        limit=account_limit,
        window_seconds=account_window,
        now_seconds=second,
    )
    allowed &= consume_rate_limit(
        "time-machine-network",
        client_address(request) or "unavailable",
        limit=network_limit,
        window_seconds=network_window,
        now_seconds=second,
    )
    if not allowed:
        return error(request, 429, "rate_limited", "Too many Time Machine requests.")
    target, mode = normalize_time_machine_target(target_time, now)
    target = target.replace(second=0, microsecond=0)
    cutoff = now.replace(second=0, microsecond=0)
    decision = serve_resolution(selected, target, cutoff)
    return {
        "venue": serialize_venue(selected),
        "mode": mode,
        "target_time": target,
        "knowledge_cutoff": cutoff,
        "cover": serialize_decision(decision, target, cutoff),
    }
