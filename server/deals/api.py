from config.network import client_address
from config.schemas import ErrorSchema
from covers.api import CACHEABLE_OPENAPI, conditional_response, find_venue
from covers.services import generation_time, serialize_venue, service_date_for
from django.db.models import Q
from django.http import HttpResponse
from identity.auth import installation_auth, session_auth
from ninja import Header, Query, Router, Status
from submissions.rate_limits import SubmissionRateLimited
from submissions.services import IdempotencyConflict, InvalidInstallationActor, UnknownVenue
from venues.models import Venue

from deals.models import DealDefinition, DealPrediction, DealPredictionRelease, HistoricalDealFact
from deals.names import public_deal_name
from deals.schemas import (
    DealEvidenceInputSchema,
    DealEvidenceReceiptSchema,
    DealSlateSchema,
    DealSuggestionsSchema,
    VenueDealsSchema,
)
from deals.search import normalize_deal_search_text
from deals.services import (
    InvalidCorrectionLineage,
    InvalidDealTarget,
    InvalidServiceDate,
    accept_deal_evidence,
    resolve_deal_evidence,
    serialize_deal,
)

router = Router(tags=["Deals"])


def venue_deals(venue: Venue, service_date=None) -> dict:
    if service_date is None:
        service_date = service_date_for(generation_time())
    release = DealPredictionRelease.objects.filter(is_authoritative=True).first()
    predictions = (
        DealPrediction.objects.none()
        if release is None
        else DealPrediction.objects.filter(
            release=release,
            venue=venue,
            service_date_local=service_date,
            deal_definition__is_active=True,
        )
        .select_related("deal_definition")
        .order_by("rank", "deal_definition__display_name", "id")
    )
    serialized = [
        serialize_deal(prediction.deal_definition, prediction=prediction)
        for prediction in predictions
    ]
    if release is None:
        serialized = [
            serialize_deal(deal)
            for deal in DealDefinition.objects.filter(venue=venue, is_active=True).order_by(
                "display_name", "id"
            )
        ]
    serialized = resolve_deal_evidence(venue, service_date, serialized)
    return {
        "venue": serialize_venue(venue),
        "deals": serialized,
    }


@router.get(
    "/deals",
    response={200: DealSlateSchema, 304: None},
    operation_id="getDealSlate",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_deal_slate(
    request, response: HttpResponse, if_none_match: str | None = Header(None, alias="If-None-Match")
):
    now = generation_time()
    generated_at = now
    body = {
        "service_date": service_date_for(now),
        "generated_at": generated_at,
        "venues": [
            venue_deals(venue, service_date_for(now))
            for venue in Venue.objects.filter(is_active=True)
        ],
    }
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body


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
    query = q.strip()
    normalized_query = normalize_deal_search_text(query)
    facts = HistoricalDealFact.objects.filter(
        family__isnull=False,
        venue__is_active=True,
    ).select_related("family", "venue")
    if query:
        search_filter = (
            Q(family__canonical_name__icontains=query)
            | Q(family__aliases__alias__icontains=query)
            | Q(display_name__icontains=query)
            | Q(unit__icontains=query)
        )
        if normalized_query:
            search_filter |= Q(private_search_text__contains=normalized_query)
        facts = facts.filter(search_filter)
    if category:
        facts = facts.filter(category=category)
    selected = None
    if venue:
        selected = find_venue(venue)
        if selected is None:
            return {"suggestions": []}

    # One canonical family can contain several intentionally distinct concrete
    # offers (for example $3 wells and $5 wells, or bottle and pitcher shapes).
    # Search and limit concrete variants rather than collapsing a family to its
    # latest fact. Repeated historical occurrences of the same shape collapse to
    # the latest representative while retaining their frequency for ranking.
    variants: dict[tuple, list[HistoricalDealFact]] = {}
    for fact in facts.distinct().order_by("family_id", "service_date_local", "source_record_key"):
        variants.setdefault(_suggestion_variant_key(fact), []).append(fact)

    ranked = []
    for rows in variants.values():
        is_venue_shape = selected is not None and any(row.venue_id == selected.id for row in rows)
        fact = max(
            rows,
            key=lambda row: (
                selected is not None and row.venue_id == selected.id,
                row.service_date_local,
                row.source_record_key,
            ),
        )
        family = fact.family
        if family is None:
            continue
        matched_source, matched_text = _suggestion_match(family, fact, query, normalized_query)
        match_rank = {
            "canonical": 0,
            "alias": 1,
            "historical_alias": 2,
            "display_name": 3,
            "unit": 4,
            None: 5,
        }[matched_source]
        last_seen = max(row.service_date_local for row in rows)
        ranked.append(
            (
                match_rank,
                0 if is_venue_shape else 1,
                -last_seen.toordinal(),
                -len(rows),
                family.canonical_name.casefold(),
                fact.display_name.casefold(),
                fact.source_record_key,
                fact,
                matched_source,
                matched_text,
                is_venue_shape,
                last_seen,
            )
        )

    suggestions = []
    for (
        *_rank,
        fact,
        matched_source,
        matched_text,
        is_venue_shape,
        last_seen,
    ) in sorted(ranked)[:limit]:
        family = fact.family
        if family is None:
            continue
        timing_description, timing_known = _suggestion_timing(fact)
        suggestions.append(
            {
                "canonical_family_id": fact.family_id,
                "canonical_name": family.canonical_name,
                "category": fact.category,
                "display_name": public_deal_name(
                    fact.display_name,
                    price_kind=fact.price_kind,
                    price_cents=fact.price_cents,
                    discount_percent=fact.relative_percent,
                ),
                "price_kind": fact.price_kind,
                "price_cents": fact.price_cents,
                "price_low_cents": None,
                "price_high_cents": None,
                "discount_percent": (
                    float(fact.relative_percent) if fact.relative_percent is not None else None
                ),
                "unit": fact.unit,
                "serving_format": "",
                "timing_description": timing_description if timing_known else None,
                "timing_known": timing_known,
                "while_supplies_last": fact.while_supplies_last,
                "source_scope": "venue" if is_venue_shape else "global",
                "last_seen_service_date_local": last_seen,
                "matched_source": matched_source,
                "matched_text": matched_text,
            }
        )
    return {"suggestions": suggestions}


def _suggestion_variant_key(fact: HistoricalDealFact) -> tuple:
    return (
        fact.family_id,
        fact.display_name,
        fact.category,
        fact.price_kind,
        fact.price_cents,
        str(fact.relative_percent) if fact.relative_percent is not None else None,
        fact.unit,
        fact.timing_kind,
        fact.timing_start_local,
        fact.timing_end_local,
        fact.timing_time_local,
        fact.while_supplies_last,
    )


def _suggestion_match(
    family, fact, query: str, normalized_query: str
) -> tuple[str | None, str | None]:
    if not query:
        return None, None
    folded_query = query.casefold()
    if folded_query in family.canonical_name.casefold():
        return "canonical", family.canonical_name
    alias = next(
        (
            candidate.alias
            for candidate in family.aliases.order_by("alias", "id")
            if folded_query in candidate.alias.casefold()
        ),
        None,
    )
    if alias is not None:
        return "alias", alias
    if normalized_query and normalized_query in fact.private_search_text:
        return "historical_alias", None
    if folded_query in fact.display_name.casefold():
        return (
            "display_name",
            public_deal_name(
                fact.display_name,
                price_kind=fact.price_kind,
                price_cents=fact.price_cents,
                discount_percent=fact.relative_percent,
            ),
        )
    if folded_query in fact.unit.casefold():
        return "unit", fact.unit
    return None, None


def _suggestion_timing(fact) -> tuple[str, bool]:
    from deals.predictor import _timing

    return _timing(fact)


@router.get(
    "/venues/{venue}/deals",
    response={200: VenueDealsSchema, 304: None, 404: ErrorSchema},
    operation_id="getVenueDeals",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_venue_deals(
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
    body = venue_deals(selected, service_date_for(generation_time()))
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body


@router.post(
    "/deal-evidence",
    auth=installation_auth,
    response={
        201: DealEvidenceReceiptSchema,
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
    session_account = (
        session_auth.authenticate(request, x_session_token) if x_session_token else None
    )
    try:
        receipt = accept_deal_evidence(
            request.auth,
            payload,
            remote_address=client_address(request),
            session_account=session_account,
        )
    except IdempotencyConflict:
        return Status(
            409,
            {
                "code": "idempotency_conflict",
                "message": "That submission ID was already used for different content.",
                "request_id": request.request_id,
            },
        )
    except SubmissionRateLimited:
        return Status(
            429,
            {
                "code": "rate_limited",
                "message": "Too many reports were submitted.",
                "request_id": request.request_id,
            },
        )
    except UnknownVenue:
        code, message = "unknown_venue", "The venue is not active or does not exist."
    except InvalidInstallationActor:
        code, message = (
            "invalid_installation_token",
            "The installation credential is invalid or expired.",
        )
    except InvalidDealTarget:
        code, message = "invalid_deal_target", "The target deal does not belong to this venue."
    except InvalidCorrectionLineage:
        code, message = "invalid_evidence_lineage", "The superseded evidence event does not exist."
    except InvalidServiceDate:
        code, message = (
            "invalid_service_date",
            "The service date must match the observed Chicago service night.",
        )
    else:
        return Status(201, receipt)
    return Status(
        422,
        {"code": code, "message": message, "request_id": request.request_id},
    )
