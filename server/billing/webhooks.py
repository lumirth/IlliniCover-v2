import hashlib
import hmac
import time
import uuid

from django.conf import settings
from product.models import Account, RevenueCatEvent

from billing.revenuecat import reconcile_account


def verify_revenuecat_signature(payload, header, secret, *, now=None, tolerance=300):
    try:
        parts = dict(part.split("=", 1) for part in header.split(","))
        timestamp, supplied = parts["t"], parts["v1"]
        timestamp_value = int(timestamp)
    except KeyError, ValueError:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    current = int(time.time()) if now is None else now
    return hmac.compare_digest(expected, supplied) and abs(current - timestamp_value) <= tolerance


def verify_revenuecat_request(request):
    authorization = settings.REVENUECAT_WEBHOOK_AUTHORIZATION
    secret = settings.REVENUECAT_WEBHOOK_SIGNING_SECRET
    return bool(
        authorization
        and secret
        and hmac.compare_digest(authorization, request.headers.get("Authorization", ""))
        and verify_revenuecat_signature(
            request.body,
            request.headers.get("X-RevenueCat-Webhook-Signature", ""),
            secret,
            tolerance=settings.REVENUECAT_WEBHOOK_TOLERANCE_SECONDS,
        )
    )


def _accounts(event):
    values = [
        event.app_user_id,
        event.original_app_user_id,
        *event.aliases,
        *event.transferred_from,
        *event.transferred_to,
    ]
    ids = []
    for value in values:
        try:
            account_id = uuid.UUID(value)
        except TypeError, ValueError:
            continue
        if account_id not in ids:
            ids.append(account_id)
    found = {account.pk: account for account in Account.objects.filter(pk__in=ids)}
    return [found[account_id] for account_id in ids if account_id in found]


def accept_revenuecat_event(envelope):
    event = envelope.event
    record = RevenueCatEvent.objects.filter(provider_event_id=event.id).first()
    if record:
        return record, True
    accounts = _accounts(event)
    for account in accounts:
        reconcile_account(account)
    record, created = RevenueCatEvent.objects.get_or_create(provider_event_id=event.id)
    return record, not created
