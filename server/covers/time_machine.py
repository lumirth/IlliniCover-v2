from datetime import datetime, timedelta

from django.conf import settings


def normalize_time_machine_target(
    target_time: datetime, knowledge_cutoff: datetime
) -> tuple[datetime, str]:
    """Return one server-authoritative Time Machine mode and effective target."""

    tolerance = timedelta(seconds=settings.TIME_MACHINE_CURRENT_TOLERANCE_SECONDS)
    if target_time < knowledge_cutoff - tolerance:
        return target_time, "past"
    if target_time > knowledge_cutoff + tolerance:
        return target_time, "future"
    return knowledge_cutoff, "current"
