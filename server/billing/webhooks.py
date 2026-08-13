import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from identity.models import Account

from billing.models import AccountEntitlement, RevenueCatEvent
from billing.revenuecat import RevenueCatRequestError, reconcile_account
from billing.schemas import RevenueCatEnvelopeSchema

SNAPSHOT_EVENT_TYPES = {
    "INITIAL_PURCHASE",
    "NON_RENEWING_PURCHASE",
    "RENEWAL",
    "PRODUCT_CHANGE",
    "CANCELLATION",
    "UNCANCELLATION",
    "BILLING_ISSUE",
    "SUBSCRIBER_ALIAS",
    "EXPIRATION",
}

REDACTED_EVENT_PAYLOAD = {"redacted": True}


def verify_revenuecat_signature(
    payload: bytes, header: str, secret: str, *, now: int | None = None, tolerance: int = 300
) -> bool:
    try:
        parts = dict(part.split("=", 1) for part in header.split(","))
        timestamp = parts["t"]
        supplied = parts["v1"]
        timestamp_value = int(timestamp)
    except KeyError, ValueError:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        return False
    current = int(time.time()) if now is None else now
    return abs(current - timestamp_value) <= tolerance


def verify_revenuecat_request(request) -> bool:
    expected_authorization = settings.REVENUECAT_WEBHOOK_AUTHORIZATION
    signing_secret = settings.REVENUECAT_WEBHOOK_SIGNING_SECRET
    if not expected_authorization or not signing_secret:
        return False
    supplied_authorization = request.headers.get("Authorization", "")
    if not hmac.compare_digest(expected_authorization, supplied_authorization):
        return False
    return verify_revenuecat_signature(
        request.body,
        request.headers.get("X-RevenueCat-Webhook-Signature", ""),
        signing_secret,
        tolerance=settings.REVENUECAT_WEBHOOK_TOLERANCE_SECONDS,
    )


@transaction.atomic
def accept_revenuecat_event(envelope: RevenueCatEnvelopeSchema) -> tuple[RevenueCatEvent, bool]:
    event_payload = envelope.event.model_dump(mode="json", by_alias=True)
    account_ids = sorted(
        filter(None, (_uuid_or_none(value) for value in _identity_values(event_payload))),
        key=str,
    )
    if account_ids:
        # Account deletion takes the same row lock before its provider-event
        # scan. Every event that still resolves to an account therefore commits
        # before that scan or observes the account as already deleted.
        list(
            Account.objects.select_for_update()
            .filter(pk__in=account_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
    # Durable webhook authority is the provider event ID plus normalized
    # entitlement rows. Never persist RevenueCat's raw alias/transfer graph:
    # it can contain identifiers for accounts that were already deleted.
    known_accounts = _known_accounts(_identity_values(event_payload))
    normalized_account_id = str(known_accounts[0].pk) if known_accounts else ""
    environment = _event_environment(envelope.event.environment)
    event, created = RevenueCatEvent.objects.get_or_create(
        provider_event_id=envelope.event.id,
        defaults={
            "event_type": envelope.event.type,
            "environment": environment,
            "app_user_id": normalized_account_id,
            "payload": REDACTED_EVENT_PAYLOAD,
        },
    )
    if not created:
        return event, True
    mirror_event(event, event_payload)
    return event, False


def mirror_event(record: RevenueCatEvent, event: dict) -> None:
    # Defense in depth for direct callers and legacy rows. No later authority
    # path needs the provider payload after this synchronous normalization.
    record.payload = REDACTED_EVENT_PAYLOAD
    event_type = str(event.get("type", ""))
    if event_type not in SNAPSHOT_EVENT_TYPES:
        if event_type == "TEST":
            record.processing_error = "non_snapshot_event_ignored"
        else:
            # RevenueCat adds provider-specific event types over time and some
            # of them (for example SUBSCRIPTION_EXTENDED and REFUND_REVERSED)
            # change entitlement state without carrying a complete snapshot.
            # Do not guess their access semantics from a partial webhook.
            # Re-read the provider's customer snapshot for every real
            # non-snapshot event associated with a known IlliniCover account.
            _reconcile_non_snapshot_event(record, event)
        # Non-snapshot payloads can contain aliases and transfer endpoints from
        # deleted accounts. The durable model already keeps the provider event
        # ID/type/environment and bounded processing result; retaining the raw
        # identity graph is unnecessary and could reintroduce erased UUIDs.
        record.processed_at = timezone.now()
        record.save(
            update_fields=["app_user_id", "payload", "processing_error", "processed_at"]
        )
        return
    known_accounts = _known_accounts(_identity_values(event))
    if not known_accounts:
        record.app_user_id = ""
        has_local_identifier_shape = any(
            _uuid_or_none(value) is not None for value in _identity_values(event)
        )
        record.processing_error = (
            "account unavailable"
            if has_local_identifier_shape
            else "app_user_id is not an IlliniCover account UUID"
        )
        record.processed_at = timezone.now()
        record.save(
            update_fields=["app_user_id", "payload", "processing_error", "processed_at"]
        )
        return
    account = Account.objects.select_for_update().filter(pk=known_accounts[0].pk).first()
    if account is None:
        # Deleted account identifiers and webhook payloads are not retained as
        # durable pseudonyms.  Provider retries remain idempotent by event ID.
        record.app_user_id = ""
        record.processing_error = "account unavailable"
        record.processed_at = timezone.now()
        record.save(update_fields=["app_user_id", "payload", "processing_error", "processed_at"])
        return
    environment = _event_environment(event.get("environment"))
    if environment == RevenueCatEvent.Environment.UNKNOWN:
        record.processing_error = "snapshot_missing_environment"
        record.processed_at = timezone.now()
        record.save(update_fields=["payload", "processing_error", "processed_at"])
        return
    # Reconciliation serializes provider reads on the account row. Take the
    # same lock before any environment-entitlement row so webhook mirroring and
    # reconciliation have one lock order (account, then entitlement), avoiding
    # an entitlement/account inversion when a negative event refreshes the
    # cross-environment provider snapshot.
    record.app_user_id = str(account.pk)
    expiration_ms = event.get("expirationAtMs")
    expires_at = (
        datetime.fromtimestamp(expiration_ms / 1000, tz=UTC) if expiration_ms is not None else None
    )
    identifier = settings.REVENUECAT_PREMIUM_ENTITLEMENT
    entitlement_ids = event.get("entitlementIds")
    if entitlement_ids is None:
        record.processing_error = "snapshot_missing_entitlement_ids"
        record.processed_at = timezone.now()
        record.save(update_fields=["payload", "processing_error", "processed_at"])
        return
    has_entitlement = identifier in entitlement_ids
    is_active = (
        has_entitlement
        and event_type != "EXPIRATION"
        and (expires_at is None or expires_at > timezone.now())
    )
    updated_ms = event.get("eventTimestampMs")
    provider_updated_at = (
        datetime.fromtimestamp(updated_ms / 1000, tz=UTC) if updated_ms is not None else None
    )
    aggregate = (
        AccountEntitlement.objects.select_for_update()
        .filter(
            account=account,
            entitlement_identifier=identifier,
            environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        )
        .first()
    )
    # Once a cross-environment provider snapshot exists, an environment event
    # cannot prove by itself whether it happened before or after that snapshot:
    # RevenueCat's event clock and our local observation clock are not a shared
    # monotonic timeline. Preserve the environment row as provenance, but keep
    # it behind the aggregate watermark until a fresh provider read below
    # confirms the current account-wide state.
    environment_authority_at = (
        record.received_at if aggregate is None else aggregate.authority_observed_at
    )
    current = (
        AccountEntitlement.objects.select_for_update()
        .filter(
            account=account,
            entitlement_identifier=identifier,
            environment=environment,
        )
        .first()
    )
    if not (
        current is not None
        and current.provider_updated_at is not None
        and (provider_updated_at is None or provider_updated_at < current.provider_updated_at)
    ):
        AccountEntitlement.objects.update_or_create(
            account=account,
            entitlement_identifier=identifier,
            environment=environment,
            defaults={
                "is_active": is_active,
                "expires_at": expires_at,
                "provider_updated_at": provider_updated_at,
                "authority_observed_at": environment_authority_at,
            },
        )
    if aggregate is not None:
        # No environment-specific event can order itself safely against an
        # existing cross-environment snapshot. Refresh immediately for both
        # positive and negative events. On provider failure, the preserved
        # event remains behind the aggregate rather than granting stale or
        # ambiguous access; the durable pending state is retried nightly.
        try:
            reconcile_account(account)
        except RevenueCatRequestError:
            record.processing_error = "snapshot_reconcile_pending"
        else:
            record.processing_error = "snapshot_reconciled"
    record.processed_at = timezone.now()
    record.save(update_fields=["app_user_id", "payload", "processing_error", "processed_at"])


def _event_environment(value) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "sandbox":
        return RevenueCatEvent.Environment.SANDBOX
    if normalized == "production":
        return RevenueCatEvent.Environment.PRODUCTION
    return RevenueCatEvent.Environment.UNKNOWN


def _identity_values(event: dict) -> list[str]:
    return [
        event.get("appUserId"),
        event.get("originalAppUserId"),
        *(event.get("aliases") or []),
        *(event.get("transferredFrom") or []),
        *(event.get("transferredTo") or []),
    ]


def _known_accounts(identifiers) -> list[Account]:
    account_ids = []
    for identifier in identifiers:
        parsed = _uuid_or_none(identifier)
        if parsed is not None and parsed not in account_ids:
            account_ids.append(parsed)
    accounts = {account.pk: account for account in Account.objects.filter(pk__in=account_ids)}
    return [accounts[account_id] for account_id in account_ids if account_id in accounts]


def _reconcile_non_snapshot_event(record: RevenueCatEvent, event: dict) -> None:
    accounts = _known_accounts(_identity_values(event))
    if not accounts:
        record.app_user_id = ""
        record.processing_error = "non_snapshot_event_no_known_account"
        return
    # A single string cannot truthfully represent a multi-account transfer.
    # Keep one local reference only when it is unambiguous; the in-memory
    # account list below still drives reconciliation for every survivor.
    record.app_user_id = str(accounts[0].pk) if len(accounts) == 1 else ""
    try:
        for account in accounts:
            reconcile_account(account)
    except RevenueCatRequestError:
        # The durable event retains a bounded pending state. The nightly
        # all-account reconciliation retries without relying on a webhook retry.
        record.processing_error = "non_snapshot_reconcile_pending"
    else:
        record.processing_error = "non_snapshot_reconciled"


def _uuid_or_none(value):
    try:
        return uuid.UUID(value)
    except TypeError, ValueError:
        return None
