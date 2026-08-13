import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from identity.models import Account

from billing.models import AccountEntitlement, ProviderDeletionRequest


class RevenueCatRequestError(Exception):
    pass


def _store_provider_aggregate(
    account: Account,
    *,
    snapshot_started_at,
    is_active: bool,
    expires_at,
) -> bool:
    """Store a provider snapshot only if no newer reconciliation already won."""

    lookup = {
        "account": account,
        "entitlement_identifier": settings.REVENUECAT_PREMIUM_ENTITLEMENT,
        "environment": AccountEntitlement.Environment.PROVIDER_AGGREGATE,
    }
    values = {
        "is_active": is_active,
        "expires_at": expires_at,
        "provider_updated_at": snapshot_started_at,
        "authority_observed_at": snapshot_started_at,
        "updated_at": timezone.now(),
    }
    with transaction.atomic():
        updated = AccountEntitlement.objects.filter(
            **lookup,
        ).filter(
            Q(authority_observed_at__lte=snapshot_started_at)
        ).update(**values)
        if updated:
            return True
        if AccountEntitlement.objects.filter(**lookup).exists():
            return False
        try:
            with transaction.atomic():
                AccountEntitlement.objects.create(**lookup, **values)
            return True
        except IntegrityError:
            # Another request created the row after our absence check. Its
            # authority watermark decides which provider snapshot may win.
            return bool(
                AccountEntitlement.objects.filter(
                    **lookup,
                    authority_observed_at__lte=snapshot_started_at,
                ).update(**values)
            )


def _request(method: str, app_user_id: str) -> tuple[int, bytes]:
    if not settings.REVENUECAT_SECRET_API_KEY:
        raise RevenueCatRequestError("api_key_missing")
    request = Request(
        "https://api.revenuecat.com/v2/projects/"
        f"{quote(settings.REVENUECAT_PROJECT_ID, safe='')}/customers/"
        f"{quote(app_user_id, safe='')}",
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


def reconcile_account(account: Account) -> None:
    # Serialize provider reads for one account, not merely their later writes.
    # Otherwise request A can start first, observe RevenueCat after request B,
    # and then have its newer provider state rejected solely because A's local
    # start clock was older. The account row is the ordinary PostgreSQL lock
    # boundary shared by webhook-triggered and scheduled reconciliation.
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        # This is the authority watermark for the provider snapshot, not the
        # later time at which its HTTP response happened to be written locally.
        # A webhook mirrored while the request is in flight remains newer than
        # this snapshot and overlays it until the next reconciliation.
        snapshot_started_at = timezone.now()
        status, body = _request("GET", str(account.pk))
        if status == 404:
            _store_provider_aggregate(
                account,
                snapshot_started_at=snapshot_started_at,
                is_active=False,
                expires_at=None,
            )
            return
        if status != 200:
            raise RevenueCatRequestError(f"unexpected_status_{status}")
        try:
            active_entitlements = json.loads(body)["active_entitlements"]["items"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RevenueCatRequestError("invalid_response") from error
        entitlement = next(
            (
                item
                for item in active_entitlements
                if item.get("entitlement_id")
                == settings.REVENUECAT_PREMIUM_ENTITLEMENT_RESOURCE_ID
            ),
            None,
        )
        expiration_ms = entitlement.get("expires_at") if entitlement else None
        expires_at = (
            datetime.fromtimestamp(expiration_ms / 1000, tz=UTC)
            if expiration_ms is not None
            else None
        )
        _store_provider_aggregate(
            account,
            snapshot_started_at=snapshot_started_at,
            is_active=entitlement is not None
            and (expires_at is None or expires_at > timezone.now()),
            expires_at=expires_at,
        )


def _complete_deletion(request: ProviderDeletionRequest) -> bool:
    request.status = ProviderDeletionRequest.Status.SUCCEEDED
    request.completed_at = timezone.now()
    request.last_error_code = ""
    request.save(
        update_fields=[
            "attempts",
            "last_attempt_at",
            "status",
            "completed_at",
            "last_error_code",
        ]
    )
    # Once RevenueCat confirms absence, retaining its customer identifier would
    # itself violate the account-erasure boundary.
    request.delete()
    return True


def process_deletion(request: ProviderDeletionRequest) -> bool:
    """Advance one durable RevenueCat erasure request.

    RevenueCat DELETE 202 means only that an asynchronous deletion was queued.
    Keep the receipt and poll the customer resource on later nightly runs until
    the provider confirms absence with 404. Synchronous 200 and already-absent
    404 DELETE responses are terminal.
    """

    request.attempts += 1
    request.last_attempt_at = timezone.now()
    method = "GET" if request.status == ProviderDeletionRequest.Status.QUEUED else "DELETE"
    try:
        status, _body = _request(method, request.provider_customer_id)
    except RevenueCatRequestError as error:
        request.last_error_code = str(error)
        request.save(update_fields=["attempts", "last_attempt_at", "last_error_code"])
        raise

    if method == "GET":
        if status == 404:
            return _complete_deletion(request)
        if status == 200:
            request.last_error_code = ""
            request.save(update_fields=["attempts", "last_attempt_at", "last_error_code"])
            return False
        request.last_error_code = f"unexpected_status_{status}"
        request.save(update_fields=["attempts", "last_attempt_at", "last_error_code"])
        raise RevenueCatRequestError(request.last_error_code)

    if status in {200, 404}:
        return _complete_deletion(request)
    if status == 202:
        request.status = ProviderDeletionRequest.Status.QUEUED
        request.last_error_code = ""
        request.save(update_fields=["attempts", "last_attempt_at", "status", "last_error_code"])
        return False
    else:
        request.last_error_code = f"unexpected_status_{status}"
        request.save(update_fields=["attempts", "last_attempt_at", "last_error_code"])
        raise RevenueCatRequestError(request.last_error_code)
