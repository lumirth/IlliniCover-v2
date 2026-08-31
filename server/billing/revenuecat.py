import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from product.models import AccountEntitlement, ProviderDeletionRequest


class RevenueCatRequestError(Exception):
    pass


def _request(method, customer_id):
    if not settings.REVENUECAT_SECRET_API_KEY:
        raise RevenueCatRequestError("api_key_missing")
    project = quote(settings.REVENUECAT_PROJECT_ID, safe="")
    customer = quote(customer_id, safe="")
    request = Request(
        f"https://api.revenuecat.com/v2/projects/{project}/customers/{customer}",
        method=method,
        headers={"Authorization": f"Bearer {settings.REVENUECAT_SECRET_API_KEY}"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except HTTPError as error:
        if error.code == 404:
            return 404, b""
        raise RevenueCatRequestError(f"http_{error.code}") from error
    except (TimeoutError, URLError) as error:
        raise RevenueCatRequestError("network_error") from error


def reconcile_account(account):
    status, body = _request("GET", str(account.pk))
    if status == 404:
        AccountEntitlement.objects.update_or_create(
            account=account, defaults={"is_active": False, "expires_at": None}
        )
        return
    try:
        items = json.loads(body)["active_entitlements"]["items"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RevenueCatRequestError("invalid_response") from error
    item = next(
        (
            value
            for value in items
            if value.get("entitlement_id") == settings.REVENUECAT_PREMIUM_ENTITLEMENT_RESOURCE_ID
        ),
        None,
    )
    expires_ms = item.get("expires_at") if item else None
    expires = datetime.fromtimestamp(expires_ms / 1000, tz=UTC) if expires_ms else None
    AccountEntitlement.objects.update_or_create(
        account=account,
        defaults={
            "is_active": bool(item and (expires is None or expires > timezone.now())),
            "expires_at": expires,
        },
    )


def process_deletion(deletion: ProviderDeletionRequest):
    method = "GET" if deletion.queued else "DELETE"
    try:
        status, _ = _request(method, deletion.provider_customer_id)
    except RevenueCatRequestError:
        return False
    if status in {200, 404} and (method == "DELETE" or status == 404):
        deletion.delete()
        return True
    if status == 202 and not deletion.queued:
        deletion.queued = True
        deletion.save(update_fields=["queued"])
    return False
