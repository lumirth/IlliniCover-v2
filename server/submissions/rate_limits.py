import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from identity.models import InstallationActor

from submissions.models import SubmissionRateBucket


class SubmissionRateLimited(Exception):
    pass


def _bucket(key: str, window_seconds: int, now_seconds: int) -> str:
    return f"report-rate:{key}:{now_seconds // window_seconds}"


def _consume(key: str, limit: int, window_seconds: int, now_seconds: int) -> bool:
    cache_key = _bucket(key, window_seconds, now_seconds)
    expires_at = datetime.fromtimestamp(
        (now_seconds // window_seconds + 1) * window_seconds, tz=UTC
    ) + timedelta(seconds=1)
    with transaction.atomic():
        bucket = SubmissionRateBucket.objects.select_for_update().filter(pk=cache_key).first()
        if bucket is None:
            try:
                with transaction.atomic():
                    SubmissionRateBucket.objects.create(
                        key=cache_key, count=1, expires_at=expires_at
                    )
            except IntegrityError:
                bucket = SubmissionRateBucket.objects.select_for_update().get(pk=cache_key)
            else:
                return True
        bucket.count += 1
        bucket.save(update_fields=["count"])
        return bucket.count <= limit


def _network_key(address: str | None) -> str | None:
    if not address:
        return None
    value = hmac.new(
        settings.NETWORK_METADATA_PEPPER.encode(), address.encode(), hashlib.sha256
    ).hexdigest()
    return value[:24]


def enforce_submission_limits(
    actor: InstallationActor,
    *,
    account_id: uuid.UUID | None,
    venue_id,
    remote_address: str | None,
    now_seconds: int,
) -> None:
    dimensions = {
        "actor": str(actor.id),
        "account": str(account_id) if account_id else None,
        "venue": str(venue_id),
        "network": _network_key(remote_address),
    }
    for dimension, value in dimensions.items():
        if value is None:
            continue
        limit, window = settings.SUBMISSION_RATE_LIMITS[dimension]
        if not _consume(f"{dimension}:{value}", limit, window, now_seconds):
            raise SubmissionRateLimited


def consume_rate_limit(
    namespace: str, identifier: str, *, limit: int, window_seconds: int, now_seconds: int
) -> bool:
    """Consume a bounded generic application rate bucket without storing raw network data."""

    return _consume(
        f"{namespace}:{identifier}",
        limit,
        window_seconds,
        now_seconds,
    )
