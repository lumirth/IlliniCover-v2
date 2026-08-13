import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
ERASED_INDEPENDENCE_NAMESPACE = uuid.UUID("8b33d657-d465-47fb-9fb7-52a14bde38df")


def erased_independence_group_key(venue_id, observed_at: datetime) -> uuid.UUID:
    """Conservatively group erased evidence without retaining a user pseudonym.

    Every erased contributor at one venue/service night collapses into one
    public-evidence bucket. The key changes across venues and nights and is
    derived only from public context, so it cannot link an erased person while
    repeated report/rotation cycles cannot manufacture independent consensus.
    """

    local = observed_at.astimezone(CHICAGO)
    if local.hour < 5:
        local -= timedelta(days=1)
    return uuid.uuid5(
        ERASED_INDEPENDENCE_NAMESPACE,
        f"{venue_id}:{local.date().isoformat()}",
    )
