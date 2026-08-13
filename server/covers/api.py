import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta

from billing.entitlements import account_has_premium
from config.logging import generalized_request_route
from config.network import keyed_client_identity
from config.schemas import ErrorSchema
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from identity.auth import session_auth
from ninja import Header, Router, Status
from submissions.rate_limits import consume_rate_limit
from venues.models import Venue

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
    persist_resolution,
    recent_reports,
    reconstruct_at,
    report_history,
    serialize_decision,
    serialize_venue,
    serve_resolution,
    service_date_for,
)
from covers.time_machine import normalize_time_machine_target

router = Router(tags=["Cover"])
decision_logger = logging.getLogger("illinicover.cover")

CACHEABLE_OPENAPI = {
    "responses": {
        200: {
            "headers": {
                "ETag": {
                    "description": "Opaque validator for a later If-None-Match request.",
                    "schema": {"type": "string"},
                }
            }
        },
        304: {
            "description": "The representation still matches If-None-Match.",
            "headers": {
                "ETag": {
                    "description": "The current representation validator.",
                    "schema": {"type": "string"},
                }
            },
        },
    }
}


def find_venue(value: str) -> Venue | None:
    query = Q(slug=value)
    try:
        query |= Q(pk=uuid.UUID(value))
    except ValueError:
        pass
    return Venue.objects.filter(query, is_active=True).first()


def conditional_response(
    response: HttpResponse, body: dict, if_none_match: str | None
) -> HttpResponse | None:
    encoded = json.dumps(body, sort_keys=True, cls=DjangoJSONEncoder, separators=(",", ":"))
    response["ETag"] = f'"{hashlib.sha256(encoded.encode()).hexdigest()}"'
    response["Cache-Control"] = "private, max-age=15"
    if if_none_match == response["ETag"]:
        not_modified = HttpResponse(status=304)
        not_modified["ETag"] = response["ETag"]
        not_modified["Cache-Control"] = response["Cache-Control"]
        return not_modified
    return None


@router.get(
    "/cover",
    response={200: CoverBoardSchema, 304: None},
    operation_id="getCoverBoard",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_cover_board(
    request, response: HttpResponse, if_none_match: str | None = Header(None, alias="If-None-Match")
):
    body = cover_board()
    not_modified = conditional_response(response, body, if_none_match)
    status_code = 304 if not_modified else 200
    for card in body["venues"]:
        decision_id = card["cover"].get("decision_id")
        if decision_id is None:
            continue
        decision_logger.info(
            "cover.decision_served",
            extra={
                "request_id": request.request_id,
                "decision_id": str(decision_id),
                "endpoint": generalized_request_route(request),
                "status_code": status_code,
            },
        )
    if not_modified:
        return not_modified
    return body


@router.get(
    "/venues/{venue}/cover",
    response={200: VenueCoverDetailSchema, 304: None, 404: ErrorSchema},
    operation_id="getVenueCover",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_venue_cover(
    request,
    venue: str,
    response: HttpResponse,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
):
    selected = find_venue(venue)
    if selected is None:
        return Status(
            404,
            {
                "code": "venue_not_found",
                "message": "That venue was not found.",
                "request_id": request.request_id,
            },
        )
    from deals.api import venue_deals

    now = current_time()
    generated = current_generation_cutoff(now)
    decision = serve_resolution(selected, generated, generated)
    request.decision_id = decision.id if decision is not None else None

    body = {
        "venue": serialize_venue(selected),
        "cover": serialize_decision(decision, generated),
        "recent_reports": recent_reports(selected, moment=now),
        "vibes": current_vibes(selected, now=now),
        "deals": venue_deals(selected, service_date_for(generated))["deals"],
    }
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body


@router.get(
    "/venues/{venue}/cover/history",
    response={200: CoverHistorySchema, 304: None, 404: ErrorSchema},
    operation_id="getVenueCoverHistory",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_venue_cover_history(
    request,
    venue: str,
    response: HttpResponse,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
):
    selected = find_venue(venue)
    if selected is None:
        return Status(
            404,
            {
                "code": "venue_not_found",
                "message": "That venue was not found.",
                "request_id": request.request_id,
            },
        )
    now = current_time()
    account = session_auth.authenticate(request, x_session_token) if x_session_token else None
    premium = account is not None and account_has_premium(account)
    history = report_history(selected, moment=now, premium=premium)
    body = {
        "venue": serialize_venue(selected),
        "service_date": service_date_for(now),
        **history,
    }
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body


@router.get(
    "/venues/{venue}/cover/time-machine",
    auth=session_auth,
    response={
        200: TimeMachineSchema,
        403: ErrorSchema,
        404: ErrorSchema,
        422: ErrorSchema,
        429: ErrorSchema,
    },
    operation_id="getVenueCoverTimeMachine",
    by_alias=True,
)
def get_venue_time_machine(request, venue: str, target_time: datetime):
    selected = find_venue(venue)
    if selected is None:
        return Status(
            404,
            {
                "code": "venue_not_found",
                "message": "That venue was not found.",
                "request_id": request.request_id,
            },
        )
    if not account_has_premium(request.auth):
        return Status(
            403,
            {
                "code": "premium_required",
                "message": "IlliniCover Blue is required for Time Machine.",
                "request_id": request.request_id,
            },
        )
    if timezone.is_naive(target_time):
        return Status(
            422,
            {
                "code": "timezone_required",
                "message": "target_time must include an explicit UTC offset.",
                "request_id": request.request_id,
            },
        )
    # The visual-acceptance and canonical-fixture settings provide an explicit
    # clock. Using the same clock here keeps GET -> premium GET scenarios
    # coherent without changing production, where current_time is real time.
    knowledge_cutoff = current_time()
    earliest = knowledge_cutoff - timedelta(days=settings.TIME_MACHINE_MAX_PAST_DAYS)
    latest = knowledge_cutoff + timedelta(days=settings.TIME_MACHINE_MAX_FUTURE_DAYS)
    if target_time < earliest or target_time > latest:
        return Status(
            422,
            {
                "code": "unsupported_target_time",
                "message": "That target is outside the supported Time Machine window.",
                "request_id": request.request_id,
            },
        )
    limit, window_seconds = settings.TIME_MACHINE_ACCOUNT_RATE_LIMIT
    network_limit, network_window = settings.TIME_MACHINE_NETWORK_RATE_LIMIT
    now_seconds = int(knowledge_cutoff.timestamp())
    account_allowed = consume_rate_limit(
        "time-machine-account",
        str(request.auth.pk),
        limit=limit,
        window_seconds=window_seconds,
        now_seconds=now_seconds,
    )
    network_allowed = consume_rate_limit(
        "time-machine-network",
        keyed_client_identity(request),
        limit=network_limit,
        window_seconds=network_window,
        now_seconds=now_seconds,
    )
    if not account_allowed or not network_allowed:
        return Status(
            429,
            {
                "code": "rate_limited",
                "message": "Too many Time Machine requests. Try again later.",
                "request_id": request.request_id,
            },
        )
    effective_target, mode = normalize_time_machine_target(target_time, knowledge_cutoff)
    # Stable minute granularity prevents repeated reads from manufacturing
    # unbounded decision rows while keeping target semantics honest.
    effective_target = effective_target.replace(second=0, microsecond=0)
    stable_cutoff = knowledge_cutoff.replace(second=0, microsecond=0)
    resolution = reconstruct_at(selected, effective_target, stable_cutoff)
    state_key = hashlib.sha256(
        json.dumps(
            {
                "schema": "time_machine_served_state_v1",
                "venueId": str(selected.id),
                "targetTime": effective_target.isoformat(),
                "knowledgeCutoff": stable_cutoff.isoformat(),
                "receiptSha256": resolution.receipt_sha256(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    decision = persist_resolution(
        selected,
        effective_target,
        stable_cutoff,
        resolution,
        served_state_key=state_key,
    )
    request.decision_id = decision.id
    return {
        "venue": serialize_venue(selected),
        "mode": mode,
        "target_time": effective_target,
        # Report the exact cutoff used to reconstruct and persist this receipt.
        # The real request clock can include seconds that are intentionally not
        # admitted by the minute-stable decision boundary above.
        "knowledge_cutoff": stable_cutoff,
        "cover": serialize_decision(decision, effective_target),
    }
