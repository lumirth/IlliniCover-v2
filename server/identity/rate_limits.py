import hmac
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from product.models import RateBucket


class RateLimited(Exception):
    pass


def network_key(address: str | None) -> str | None:
    return address


def _bucket_prefix(key: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"rate\0{key}".encode(), "sha256"
    ).hexdigest()


def forget(key: str) -> None:
    RateBucket.objects.filter(key__startswith=f"{_bucket_prefix(key)}:").delete()


def consume(key: str, limit: int, window: int, now: int) -> bool:
    moment = datetime.fromtimestamp(now, tz=UTC)
    RateBucket.objects.filter(expires_at__lte=moment).delete()
    bucket_key = f"{_bucket_prefix(key)}:{now // window}"
    expiry = datetime.fromtimestamp((now // window + 1) * window, tz=UTC) + timedelta(seconds=1)
    with transaction.atomic():
        bucket = RateBucket.objects.select_for_update().filter(pk=bucket_key).first()
        if bucket is None:
            try:
                with transaction.atomic():
                    RateBucket.objects.create(key=bucket_key, count=1, expires_at=expiry)
                return True
            except IntegrityError:
                bucket = RateBucket.objects.select_for_update().get(pk=bucket_key)
        bucket.count += 1
        bucket.save(update_fields=["count"])
        return bucket.count <= limit


def enforce_installation_issuance_limit(address: str | None, *, now_seconds: int) -> None:
    identifier = network_key(address)
    if identifier:
        limit, window = settings.INSTALLATION_ISSUANCE_RATE_LIMIT
        if not consume(f"installation:{identifier}", limit, window, now_seconds):
            raise RateLimited


InstallationIssuanceRateLimited = RateLimited
