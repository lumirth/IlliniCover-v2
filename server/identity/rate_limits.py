import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction

from identity.models import IdentityRateBucket


class InstallationIssuanceRateLimited(Exception):
    pass


def _bucket(key: str, window_seconds: int, now_seconds: int) -> str:
    return f"identity-rate:{key}:{now_seconds // window_seconds}"


def _network_key(address: str | None) -> str:
    address = address or "unavailable"
    return hmac.new(
        settings.NETWORK_METADATA_PEPPER.encode(),
        address.encode(),
        hashlib.sha256,
    ).hexdigest()[:24]


def enforce_installation_issuance_limit(
    *, remote_address: str | None, now_seconds: int
) -> None:
    limit, window_seconds = settings.INSTALLATION_ISSUANCE_RATE_LIMIT
    key = _bucket(_network_key(remote_address), window_seconds, now_seconds)
    expires_at = datetime.fromtimestamp(
        (now_seconds // window_seconds + 1) * window_seconds,
        tz=UTC,
    ) + timedelta(seconds=1)
    with transaction.atomic():
        bucket = IdentityRateBucket.objects.select_for_update().filter(pk=key).first()
        if bucket is None:
            try:
                with transaction.atomic():
                    IdentityRateBucket.objects.create(
                        key=key,
                        count=1,
                        expires_at=expires_at,
                    )
            except IntegrityError:
                bucket = IdentityRateBucket.objects.select_for_update().get(pk=key)
            else:
                return
        bucket.count += 1
        bucket.save(update_fields=["count"])
        if bucket.count > limit:
            raise InstallationIssuanceRateLimited
