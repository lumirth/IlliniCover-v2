from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
SERVICE_NIGHT_CUTOFF_HOUR = 5


def require_aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("cover-model datetimes must be timezone-aware")


def service_date_for(moment: datetime) -> date:
    require_aware(moment)
    local = moment.astimezone(CHICAGO)
    if local.hour < SERVICE_NIGHT_CUTOFF_HOUR:
        local -= timedelta(days=1)
    return local.date()


def service_night_bounds(service_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(service_date, time(SERVICE_NIGHT_CUTOFF_HOUR), tzinfo=CHICAGO)
    end = datetime.combine(
        service_date + timedelta(days=1),
        time(SERVICE_NIGHT_CUTOFF_HOUR),
        tzinfo=CHICAGO,
    )
    return start, end


def service_minute(moment: datetime) -> float:
    """Minutes since the service-night cutoff, preserving continuous clock time."""

    service_date = service_date_for(moment)
    start, _ = service_night_bounds(service_date)
    # Convert to UTC before subtraction so the repeated fall-back hour remains
    # ordered and a spring-forward service night does not invent a missing hour.
    return (
        moment.astimezone(ZoneInfo("UTC")) - start.astimezone(ZoneInfo("UTC"))
    ).total_seconds() / 60.0


def same_service_night(first: datetime, second: datetime) -> bool:
    return service_date_for(first) == service_date_for(second)
