from collections import defaultdict

from config.network import client_address
from config.schemas import ErrorSchema
from covers.api import find_venue
from covers.services import current_time, serialize_venue, service_date_for
from django.db.models import Q
from identity.attribution import AccountActorMismatch
from identity.auth import installation_auth, session_auth
from ninja import Header, Query, Router, Status
from product.models import HistoricalDealFact, Venue
from submissions.rate_limits import SubmissionRateLimited
from submissions.services import IdempotencyConflict, InvalidInstallationActor, UnknownVenue

from deals.names import public_deal_name
from deals.schemas import (
    DealEvidenceInputSchema,
    DealEvidenceReceiptSchema,
    DealSlateSchema,
    DealSuggestionsSchema,
    VenueDealsSchema,
)
from deals.services import (
    InvalidDealFamily,
    InvalidDealTarget,
    InvalidServiceDate,
    accept_deal_evidence,
    resolve_deal_evidence,
    serialize_deal,
)

router = Router(tags=["Deals"])


def _fact_key(fact):
    return (
        fact.family_id,
        fact.display_name,
        fact.price_kind,
        fact.price_cents,
        fact.discount_percent,
        fact.unit,
        fact.timing_description,
        fact.while_supplies_last,
    )


def venue_deals(venue: Venue, service_date=None):
    service_date = service_date or service_date_for(current_time())
    groups = defaultdict(list)
    for fact in HistoricalDealFact.objects.filter(venue=venue).select_related("family"):
        if fact.service_date_local.weekday() == service_date.weekday():
            groups[_fact_key(fact)].append(fact)
    ranked = sorted(
        groups.values(),
        key=lambda rows: (
            len({row.service_date_local for row in rows}),
            max(row.service_date_local for row in rows),
        ),
        reverse=True,
    )
    deals = [
        serialize_deal(max(rows, key=lambda row: row.service_date_local))
        for rows in ranked
        if len({row.service_date_local for row in rows}) >= 2
    ][:12]
    return {
        "venue": serialize_venue(venue),
        "deals": resolve_deal_evidence(venue, service_date, deals),
    }


@router.get("/deals", response=DealSlateSchema, operation_id="getDealSlate", by_alias=True)
def get_deal_slate(request):
    now = current_time()
    day = service_date_for(now)
    return {
        "service_date": day,
        "generated_at": now,
        "venues": [venue_deals(venue, day) for venue in Venue.objects.filter(is_active=True)],
    }


@router.get(
    "/deal-suggestions",
    response=DealSuggestionsSchema,
    operation_id="searchDealSuggestions",
    by_alias=True,
)
def search_deal_suggestions(
    request,
    q: str = Query("", max_length=100),
    category: str | None = Query(None, max_length=40),
    venue: str | None = Query(None, max_length=80),
    limit: int = Query(6, ge=1, le=20),
):
    selected = find_venue(venue) if venue else None
    if venue and selected is None:
        return {"suggestions": []}
    facts = HistoricalDealFact.objects.filter(venue__is_active=True).select_related(
        "family", "venue"
    )
    if category:
        facts = facts.filter(family__category=category)
    query = q.strip()
    if query:
        facts = facts.filter(
            Q(display_name__icontains=query)
            | Q(unit__icontains=query)
            | Q(family__canonical_name__icontains=query)
        )
    rows = sorted(
        facts.distinct(),
        key=lambda fact: (fact.venue_id == getattr(selected, "pk", None), fact.service_date_local),
        reverse=True,
    )
    suggestions, seen = [], set()
    for fact in rows:
        key = _fact_key(fact)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            {
                "canonical_family_id": fact.family_id,
                "category": fact.family.category,
                "display_name": public_deal_name(
                    fact.display_name,
                    price_kind=fact.price_kind,
                    price_cents=fact.price_cents,
                    discount_percent=fact.discount_percent,
                ),
                "price_kind": fact.price_kind,
                "price_cents": fact.price_cents,
                "discount_percent": float(fact.discount_percent)
                if fact.discount_percent is not None
                else None,
                "unit": fact.unit,
                "serving_format": "",
                "timing_description": fact.timing_description or None,
                "timing_known": bool(fact.timing_description),
                "while_supplies_last": fact.while_supplies_last,
                "source_scope": "venue" if selected and fact.venue_id == selected.pk else "global",
                "last_seen_service_date_local": fact.service_date_local,
            }
        )
        if len(suggestions) == limit:
            break
    return {"suggestions": suggestions}


@router.get(
    "/venues/{venue}/deals",
    response={200: VenueDealsSchema, 404: ErrorSchema},
    operation_id="getVenueDeals",
    by_alias=True,
)
def get_venue_deals(request, venue: str):
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
    return venue_deals(selected)


@router.post(
    "/deal-evidence",
    auth=installation_auth,
    response={
        201: DealEvidenceReceiptSchema,
        401: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        429: ErrorSchema,
    },
    operation_id="createDealEvidence",
    by_alias=True,
)
def create_deal_evidence(
    request,
    payload: DealEvidenceInputSchema,
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
):
    account = session_auth.authenticate(request, x_session_token) if x_session_token else None
    try:
        receipt = accept_deal_evidence(
            request.auth, payload, remote_address=client_address(request), session_account=account
        )
    except IdempotencyConflict:
        code, message, status = (
            "idempotency_conflict",
            "That submission ID has different content.",
            409,
        )
    except SubmissionRateLimited:
        code, message, status = "rate_limited", "Too many reports were submitted.", 429
    except UnknownVenue:
        code, message, status = "unknown_venue", "The venue does not exist.", 422
    except InvalidInstallationActor:
        code, message, status = "invalid_installation_token", "The credential is invalid.", 401
    except InvalidDealTarget:
        code, message, status = (
            "invalid_deal_target",
            "The target does not belong to this venue.",
            422,
        )
    except InvalidDealFamily:
        code, message, status = (
            "invalid_deal_family",
            "The selected deal family is not reviewed.",
            422,
        )
    except AccountActorMismatch:
        code, message, status = (
            "installation_account_mismatch",
            "This installation belongs to another account.",
            409,
        )
    except InvalidServiceDate:
        code, message, status = (
            "invalid_service_date",
            "The service date does not match the observation.",
            422,
        )
    else:
        return Status(201, receipt)
    return Status(status, {"code": code, "message": message, "request_id": request.request_id})
