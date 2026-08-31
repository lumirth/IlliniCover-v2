import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone
from product.models import AdvertisedAdmission, Submission, Venue

CHICAGO = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")
FREE_HISTORY_NIGHTS, PREMIUM_HISTORY_NIGHTS = 7, 90
FREE_HISTORY_LIMIT, PREMIUM_HISTORY_LIMIT = 50, 250


def current_time():
    return timezone.now()


def generation_time(moment=None):
    moment = moment or current_time()
    return moment.replace(second=(moment.second // 15) * 15, microsecond=0)


def service_date_for(moment):
    local = moment.astimezone(CHICAGO)
    return (local - timedelta(days=local.hour < 5)).date()


def service_night_bounds(moment):
    day = service_date_for(moment)
    start = datetime.combine(day, time(5), tzinfo=CHICAGO)
    return start, datetime.combine(day + timedelta(days=1), time(5), tzinfo=CHICAGO)


def service_minute(moment):
    start, _ = service_night_bounds(moment)
    return (moment.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60


def serialize_venue(venue):
    return {
        "id": venue.pk,
        "slug": venue.slug,
        "name": venue.name,
        "address": venue.address,
        "opened_year": venue.opened_year,
    }


def _reduced(report):
    return report.trust.get("rapidSpam") or report.trust.get("locationSignal") == "far"


def _trusted(query):
    return [
        report
        for report in query
        if report.time_quality in {"plausible", "stale_interaction"}
        and not report.trust.get("impossibleMovement")
    ]


def _admitted(query, *, bucket_minutes=None):
    latest = {}
    for report in _trusted(query.order_by("observed_at_client", "received_at_server")):
        group = report.independence_group
        bucket = (
            int(service_minute(report.observed_at_client) // bucket_minutes)
            if bucket_minutes
            else None
        )
        key = (report.venue_id, service_date_for(report.observed_at_client), group, bucket)
        latest[key] = report
    return list(latest.values())


def _is_historical_echo(report):
    echo = report.cover_echo
    if not (
        echo.get("pricePrefilled")
        and not echo.get("priceTouched")
        and echo.get("displayedSource") == "historical"
    ):
        return False
    price = report.cover_price_cents
    if echo.get("displayedPriceKind") == "single":
        return price == echo.get("displayedAmountCents")
    low, high = echo.get("displayedLowCents"), echo.get("displayedHighCents")
    return isinstance(low, int) and isinstance(high, int) and low <= price <= high


def _corroborated(reports):
    ordinary = {
        (row.venue_id, service_date_for(row.observed_at_client), row.cover_price_cents)
        for row in reports
        if not _is_historical_echo(row)
    }
    echoes = defaultdict(set)
    for row in reports:
        if _is_historical_echo(row) and row.independence_group:
            key = (row.venue_id, service_date_for(row.observed_at_client), row.cover_price_cents)
            echoes[key].add(row.independence_group)
    return [
        row
        for row in reports
        if not _is_historical_echo(row)
        or (
            row.venue_id,
            service_date_for(row.observed_at_client),
            row.cover_price_cents,
        )
        in ordinary
        or len(
            echoes[
                (row.venue_id, service_date_for(row.observed_at_client), row.cover_price_cents)
            ]
        )
        >= 2
    ]


def _snap(value):
    return max(0, int(round(value / 500)) * 500)


def _prices(reports):
    return [report.cover_price_cents for report in reports if report.cover_price_cents is not None]


def _historical_reports(venue, target, cutoff, *, campus=False):
    target_day = service_date_for(target)
    completed_before = datetime.combine(service_date_for(cutoff), time(5), tzinfo=CHICAGO)
    query = Submission.objects.filter(
        kind=Submission.Kind.OBSERVATIONS,
        cover_price_cents__isnull=False,
        observed_at_client__lt=completed_before,
        observed_at_client__lte=cutoff,
        received_at_server__lte=cutoff,
    )
    if not campus:
        query = query.filter(venue=venue)
    minute = service_minute(target)
    return [
        row
        for row in _corroborated(_admitted(query, bucket_minutes=30))
        if not _reduced(row)
        and service_date_for(row.observed_at_client) != target_day
        and service_date_for(row.observed_at_client).weekday()
        == target_day.weekday()
        and abs(service_minute(row.observed_at_client) - minute) <= 120
    ]


def _same_night_reports(venue, target, cutoff):
    start, end = service_night_bounds(target)
    query = Submission.objects.filter(
        venue=venue,
        kind=Submission.Kind.OBSERVATIONS,
        cover_price_cents__isnull=False,
        observed_at_client__gte=start,
        observed_at_client__lt=end,
        observed_at_client__lte=min(end, cutoff),
        received_at_server__lte=cutoff,
    )
    minute = service_minute(target)
    return [
        row
        for row in _corroborated(_admitted(query, bucket_minutes=30))
        if not _reduced(row) and abs(service_minute(row.observed_at_client) - minute) <= 120
    ]


def _historical(venue, target, cutoff, *, adjust=True):
    rows = _historical_reports(venue, target, cutoff)
    if not rows:
        rows = _historical_reports(venue, target, cutoff, campus=True)
    prices = sorted(_prices(rows))
    if not prices:
        return ("unavailable", None, None, None, "unavailable", "unavailable", None)
    point = _snap(median(prices))
    original = point
    source_time = max(row.observed_at_client for row in rows)
    if adjust:
        own = _same_night_reports(venue, target, cutoff)
        if own:
            raw = median(_prices(own)) - point
            point = _snap(point + max(-1_000, min(1_000, raw * len(own) / (len(own) + 1.5))))
            source_time = max(source_time, max(row.observed_at_client for row in own))
        else:
            residuals = []
            activity: list[datetime] = []
            for other in Venue.objects.filter(is_active=True).exclude(pk=venue.pk):
                current = _same_night_reports(other, target, cutoff)
                baseline = _historical(other, target, cutoff, adjust=False)
                if current and baseline[1] is not None:
                    residuals.append(median(_prices(current)) - baseline[1])
                    activity.extend(row.observed_at_client for row in current)
            if len(residuals) >= 2:
                point = _snap(point + max(-500, min(500, median(residuals) / 2)))
                source_time = max(source_time, max(activity))
    if len(prices) >= 4:
        low, high = _snap(prices[len(prices) // 4]), _snap(prices[(len(prices) * 3) // 4])
        low, high = _snap(low + point - original), _snap(high + point - original)
        if low != high:
            return ("range", None, low, high, "historical", "historical", source_time)
    return ("single", point, None, None, "historical", "historical", source_time)


def _live_reports(venue, target, cutoff):
    if target > cutoff:
        return []
    start, end = service_night_bounds(target)
    retrospective = cutoff - target > timedelta(
        seconds=settings.TIME_MACHINE_CURRENT_TOLERANCE_SECONDS
    )
    lower = (
        start
        if retrospective
        else max(start, target - timedelta(seconds=settings.COVER_LIVE_HORIZON_SECONDS))
    )
    upper = min(end, cutoff) if retrospective else target
    query = Submission.objects.filter(
        venue=venue,
        kind=Submission.Kind.OBSERVATIONS,
        cover_price_cents__isnull=False,
        observed_at_client__gte=lower,
        observed_at_client__lte=upper,
        received_at_server__lte=cutoff,
    )
    return _corroborated(_admitted(query, bucket_minutes=30) if retrospective else _admitted(query))


def _resolve_live(reports, target, *, retrospective=False):
    if not reports:
        return None
    support: defaultdict[int, float] = defaultdict(float)
    for row in reports:
        distance = abs((target - row.observed_at_client).total_seconds())
        support[row.cover_price_cents] += (0.6 if _reduced(row) else 1) * math.exp(
            -math.log(2) * distance / 1_800
        )
    ranked = sorted(support.items(), key=lambda item: (-item[1], item[0]))
    leading, weight = ranked[0]
    material = [
        price
        for price, candidate in ranked[1:]
        if candidate >= weight * 0.6 and abs(price - leading) >= 500
    ]
    selected = {leading, *material}
    evidence = [row for row in reports if row.cover_price_cents in selected]
    evidence_time = max(row.observed_at_client for row in evidence)
    if material:
        return (
            "range",
            None,
            min(selected),
            max(selected),
            "historical" if retrospective else "mixed",
            "reconstructed_mixed" if retrospective else "live_mixed",
            evidence_time,
        )
    status = "unusual" if all(_reduced(row) for row in evidence) else (
        "reconstructed" if retrospective else "live"
    )
    return (
        "single",
        leading,
        None,
        None,
        "historical" if retrospective else "live",
        status,
        evidence_time,
    )


def _apply_advertised(venue, target, cutoff, decision):
    ads = list(
        AdvertisedAdmission.objects.filter(
            venue=venue, starts_at__lte=target, published_at__lte=cutoff, qualification=""
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=target))
        .order_by("published_at")
    )
    if not ads:
        return decision
    kind, amount, low, high, source, status, evidence_time = decision
    advertised = {row.price_cents for row in ads}
    advertised_time = max(row.published_at for row in ads)
    if (source == "unavailable" or (source == "historical" and status == "historical")) and len(
        advertised
    ) == 1:
        return (
            "single",
            advertised.pop(),
            None,
            None,
            "advertised",
            "advertised",
            advertised_time,
        )
    resolved = {amount} if kind == "single" and amount is not None else {low, high}
    prices = advertised | {value for value in resolved if value is not None}
    if len(prices) == 1:
        return decision
    return (
        "range",
        None,
        min(prices),
        max(prices),
        "mixed",
        "advertised_conflict",
        max(value for value in (evidence_time, advertised_time) if value is not None),
    )


def resolve_at(venue, target, cutoff):
    retrospective = cutoff - target > timedelta(
        seconds=settings.TIME_MACHINE_CURRENT_TOLERANCE_SECONDS
    )
    live = _resolve_live(
        _live_reports(venue, target, cutoff), target, retrospective=retrospective
    )
    return _apply_advertised(venue, target, cutoff, live or _historical(venue, target, cutoff))


def serve_resolution(venue, target, cutoff):
    return resolve_at(venue, target.replace(microsecond=0), cutoff.replace(microsecond=0))


def serialize_decision(decision, target, cutoff=None):
    if decision is None:
        return None
    cutoff = cutoff or target
    kind, price, low, high, source, status, evidence_time = decision
    return {
        "price": {"kind": kind, "amount_cents": price, "low_cents": low, "high_cents": high},
        "source": source,
        "freshness_seconds": (
            max(0, int((cutoff - evidence_time).total_seconds())) if evidence_time else None
        ),
        "status": status,
        "computed_at": cutoff,
        "target_time": target,
        "knowledge_cutoff": cutoff,
    }


def decision_for_submission(submission):
    if submission.cover_price_cents is None:
        return None
    moment = submission.received_at_server.replace(microsecond=0)
    return serve_resolution(submission.venue, moment, moment)


def _public_reports(venue, moment, window_start=None):
    start, end = service_night_bounds(moment)
    query = Submission.objects.filter(
        venue=venue,
        kind=Submission.Kind.OBSERVATIONS,
        observed_at_client__gte=window_start or start,
        observed_at_client__lt=end,
        observed_at_client__lte=moment,
        received_at_server__lte=moment,
    )
    return sorted(
        (row for row in _admitted(query) if not _reduced(row)),
        key=lambda row: row.observed_at_client,
        reverse=True,
    )


def current_vibes(venue, *, now=None):
    now = now or current_time()
    result = {"line_length": None, "line_speed": None, "crowd_level": None}
    start, end = service_night_bounds(now)
    query = Submission.objects.filter(
        venue=venue,
        kind=Submission.Kind.OBSERVATIONS,
        observed_at_client__gte=start,
        observed_at_client__lt=end,
        observed_at_client__lte=now,
        received_at_server__lte=now,
    )
    reports = sorted(
        (row for row in _trusted(query) if not _reduced(row)),
        key=lambda row: row.observed_at_client,
        reverse=True,
    )
    for report in reports:
        age = (now - report.observed_at_client).total_seconds()
        for vibe in report.vibes:
            dimension = vibe["dimension"]
            if result[dimension] is None and age <= settings.VIBE_FRESHNESS_SECONDS[dimension]:
                result[dimension] = vibe["value"]
        if all(result.values()):
            break
    return result


def recent_reports(venue, *, moment=None, limit=50, window_start=None):
    rows = []
    for report in _public_reports(venue, moment or current_time(), window_start):
        rows.append(
            {
                "observed_at": report.observed_at_client,
                "received_at": report.received_at_server,
                "price_cents": report.cover_price_cents,
                "interaction": report.cover_interaction or "vibes",
                "broad_context": {"outside": "Outside", "inside": "Inside"}.get(
                    report.vantage_point
                ),
                "vibes": [f"{vibe['dimension']}:{vibe['value']}" for vibe in report.vibes],
            }
        )
        if len(rows) == limit:
            break
    return rows


def report_history(venue, *, moment, premium):
    start, _ = service_night_bounds(moment)
    nights = PREMIUM_HISTORY_NIGHTS if premium else FREE_HISTORY_NIGHTS
    limit = PREMIUM_HISTORY_LIMIT if premium else FREE_HISTORY_LIMIT
    rows = recent_reports(
        venue, moment=moment, limit=limit + 1, window_start=start - timedelta(days=nights - 1)
    )
    return {
        "access_tier": "extended" if premium else "limited",
        "window_start": start - timedelta(days=nights - 1),
        "has_more": len(rows) > limit,
        "reports": rows[:limit],
    }


def current_generation_cutoff(now):
    bucket = generation_time(now)
    latest_report = Submission.objects.filter(
        received_at_server__gt=bucket, received_at_server__lte=now
    ).aggregate(value=Max("received_at_server"))["value"]
    latest_ad = AdvertisedAdmission.objects.filter(
        published_at__gt=bucket, published_at__lte=now
    ).aggregate(value=Max("published_at"))["value"]
    return max(value for value in (bucket, latest_report, latest_ad) if value is not None)


def cover_board(*, now=None):
    now = now or current_time()
    cutoff = current_generation_cutoff(now)
    cards = []
    for venue in Venue.objects.filter(is_active=True):
        reports = _public_reports(venue, now)
        cards.append(
            {
                "venue": serialize_venue(venue),
                "cover": serialize_decision(
                    serve_resolution(venue, cutoff, cutoff), cutoff, cutoff
                ),
                "recent_report_count": len(
                    [row for row in reports if row.cover_price_cents is not None]
                ),
                "latest_activity_at": reports[0].observed_at_client if reports else None,
                "vibes": current_vibes(venue, now=now),
            }
        )
    return {
        "service_date": service_date_for(now),
        "generated_at": cutoff,
        "server_revision": settings.CODE_REVISION,
        "venues": cards,
    }
