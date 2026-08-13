import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone as django_timezone
from identity.models import Account

from billing.entitlements import account_has_premium
from billing.models import AccountEntitlement, RevenueCatEvent
from billing.webhooks import verify_revenuecat_signature

AUTHORIZATION = "Bearer webhook-test-token"
SIGNING_SECRET = "webhook-signing-secret"


def signed_headers(body: bytes, timestamp: int) -> dict[str, str]:
    digest = hmac.new(
        SIGNING_SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": AUTHORIZATION,
        "X-RevenueCat-Webhook-Signature": f"t={timestamp},v1={digest}",
    }


def event_body(
    account: Account,
    *,
    event_id: str = "rc-event-1",
    environment: str | None = "SANDBOX",
    event_type: str = "INITIAL_PURCHASE",
) -> bytes:
    event = {
        "id": event_id,
        "type": event_type,
        "appUserId": str(account.id),
        "entitlementIds": ["premium"],
        "expirationAtMs": int((time.time() + 3600) * 1000),
        "eventTimestampMs": int(time.time() * 1000),
    }
    if environment is not None:
        event["environment"] = environment
    return json.dumps(
        {
            "apiVersion": "1.0",
            "event": event,
        },
        separators=(",", ":"),
    ).encode()


def test_signature_verifier_rejects_tampering_and_stale_replays():
    body = b'{"event":{"id":"one"}}'
    now = 1_800_000_000
    header = signed_headers(body, now)["X-RevenueCat-Webhook-Signature"]

    assert verify_revenuecat_signature(body, header, SIGNING_SECRET, now=now) is True
    assert verify_revenuecat_signature(body + b" ", header, SIGNING_SECRET, now=now) is False
    assert verify_revenuecat_signature(body, header, SIGNING_SECRET, now=now + 301) is False


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_authenticated_webhook_is_idempotent_and_mirrors_premium():
    account = Account.objects.create_user("premium@example.com")
    body = event_body(account)
    timestamp = int(time.time())
    headers = signed_headers(body, timestamp)
    client = Client()

    first = client.post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=headers,
    )
    duplicate = client.post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == {"received": True, "duplicate": False}
    assert duplicate.json() == {"received": True, "duplicate": True}
    assert RevenueCatEvent.objects.count() == 1
    event = RevenueCatEvent.objects.get()
    mirror = AccountEntitlement.objects.get(account=account)
    assert event.environment == RevenueCatEvent.Environment.SANDBOX
    assert event.app_user_id == str(account.pk)
    assert event.payload == {"redacted": True}
    assert mirror.environment == AccountEntitlement.Environment.SANDBOX
    assert mirror.is_active is True


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_sandbox_and_production_webhooks_keep_independent_entitlement_state():
    account = Account.objects.create_user("two-environments@example.com")
    client = Client()
    sandbox = event_body(account, event_id="rc-sandbox", environment="SANDBOX")
    production = event_body(
        account,
        event_id="rc-production",
        environment="PRODUCTION",
        event_type="EXPIRATION",
    )

    for body in (sandbox, production):
        response = client.post(
            "/api/v2/billing/revenuecat-webhook",
            data=body,
            content_type="application/json",
            headers=signed_headers(body, int(time.time())),
        )
        assert response.status_code == 200

    mirrors = {
        mirror.environment: mirror.is_active
        for mirror in AccountEntitlement.objects.filter(account=account)
    }
    assert mirrors == {"sandbox": True, "production": False}
    assert set(RevenueCatEvent.objects.values_list("environment", flat=True)) == {
        "sandbox",
        "production",
    }


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_snapshot_without_environment_is_retained_but_cannot_mutate_access():
    account = Account.objects.create_user("missing-environment@example.com")
    body = event_body(account, environment=None)

    response = Client().post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=signed_headers(body, int(time.time())),
    )

    assert response.status_code == 200
    record = RevenueCatEvent.objects.get()
    assert record.environment == RevenueCatEvent.Environment.UNKNOWN
    assert record.processing_error == "snapshot_missing_environment"
    assert not AccountEntitlement.objects.filter(account=account).exists()


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_webhook_for_deleted_account_does_not_retain_stable_customer_identifier():
    account = Account.objects.create_user("deleted@example.com")
    body = event_body(account)
    account.delete()
    timestamp = int(time.time())

    response = Client().post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=signed_headers(body, timestamp),
    )

    assert response.status_code == 200
    record = RevenueCatEvent.objects.get()
    assert record.app_user_id == ""
    assert record.payload == {"redacted": True}
    assert record.processing_error == "account unavailable"


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_snapshot_with_deleted_alias_retains_only_one_surviving_local_account():
    deleted = Account.objects.create_user("deleted-alias@example.com")
    survivor = Account.objects.create_user("surviving-alias@example.com")
    deleted_id = str(deleted.pk)
    survivor_id = str(survivor.pk)
    deleted.delete()
    event = {
        "id": "rc-mixed-snapshot-identities",
        "type": "INITIAL_PURCHASE",
        "appUserId": deleted_id,
        "originalAppUserId": survivor_id,
        "aliases": [deleted_id, survivor_id],
        "transferredFrom": [deleted_id],
        "transferredTo": [survivor_id],
        "entitlementIds": ["premium"],
        "expirationAtMs": int((time.time() + 3600) * 1000),
        "eventTimestampMs": int(time.time() * 1000),
        "environment": "SANDBOX",
    }
    body = json.dumps({"apiVersion": "1.0", "event": event}).encode()

    response = Client().post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=signed_headers(body, int(time.time())),
    )

    record = RevenueCatEvent.objects.get()
    rendered = json.dumps(record.payload)
    assert response.status_code == 200
    assert record.app_user_id == survivor_id
    assert record.payload == {"redacted": True}
    assert deleted_id not in rendered
    assert survivor_id not in rendered
    assert AccountEntitlement.objects.get(account=survivor).is_active is True


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_older_provider_event_cannot_overwrite_newer_entitlement_state():
    account = Account.objects.create_user("ordered@example.com")
    newer = AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        expires_at=django_timezone.now() + timedelta(days=1),
        provider_updated_at=django_timezone.now(),
    )
    body = json.dumps(
        {
            "apiVersion": "1.0",
            "event": {
                "id": "rc-event-old",
                "type": "EXPIRATION",
                "appUserId": str(account.id),
                "entitlementIds": ["premium"],
                "expirationAtMs": int((time.time() - 1) * 1000),
                "eventTimestampMs": int(
                    (newer.provider_updated_at - timedelta(minutes=5)).timestamp() * 1000
                ),
                "environment": "SANDBOX",
            },
        },
        separators=(",", ":"),
    ).encode()

    response = Client().post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=signed_headers(body, int(time.time())),
    )

    assert response.status_code == 200
    newer.refresh_from_db()
    assert newer.is_active is True
    assert newer.expires_at > django_timezone.now()


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_official_non_snapshot_and_null_entitlement_events_never_revoke_access():
    account = Account.objects.create_user("events@example.com")
    mirror = AccountEntitlement.objects.create(account=account, is_active=True)
    client = Client()
    fixtures = [
        {
            "id": "rc-transfer",
            "type": "TRANSFER",
            "original_app_user_id": str(account.id),
            "aliases": [str(account.id)],
            "entitlement_ids": None,
            "transferred_from": [str(account.id)],
            "transferred_to": [str(uuid.uuid4())],
        },
        {
            "id": "rc-temporary",
            "type": "TEMPORARY_ENTITLEMENT_GRANT",
            "app_user_id": str(account.id),
            "entitlement_ids": None,
        },
        {
            "id": "rc-test",
            "type": "TEST",
            "app_user_id": str(account.id),
            "entitlement_ids": None,
        },
    ]

    reconciled = []

    def reconcile(account_to_reconcile):
        reconciled.append(account_to_reconcile.pk)

    with patch("billing.webhooks.reconcile_account", side_effect=reconcile):
        for fixture in fixtures:
            body = json.dumps({"api_version": "1.0", "event": fixture}).encode()
            response = client.post(
                "/api/v2/billing/revenuecat-webhook",
                data=body,
                content_type="application/json",
                headers=signed_headers(body, int(time.time())),
            )
            assert response.status_code == 200

    mirror.refresh_from_db()
    assert mirror.is_active is True
    assert set(RevenueCatEvent.objects.values_list("processing_error", flat=True)) == {
        "non_snapshot_reconciled",
        "non_snapshot_event_ignored",
    }
    assert reconciled == [account.pk, account.pk]


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_transfer_reconciles_each_known_customer_and_normalizes_event_identity():
    source = Account.objects.create_user("source@example.com")
    destination = Account.objects.create_user("destination@example.com")
    event = {
        "id": "rc-transfer-two-known",
        "type": "TRANSFER",
        "entitlement_ids": None,
        "transferred_from": [str(source.pk)],
        "transferred_to": [str(destination.pk)],
    }
    body = json.dumps({"api_version": "1.0", "event": event}).encode()
    reconciled = []

    with patch(
        "billing.webhooks.reconcile_account",
        side_effect=lambda account: reconciled.append(account.pk),
    ):
        response = Client().post(
            "/api/v2/billing/revenuecat-webhook",
            data=body,
            content_type="application/json",
            headers=signed_headers(body, int(time.time())),
        )

    record = RevenueCatEvent.objects.get()
    assert response.status_code == 200
    assert reconciled == [source.pk, destination.pk]
    assert record.app_user_id == ""
    assert record.payload == {"redacted": True}
    assert record.processing_error == "non_snapshot_reconciled"


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_late_non_snapshot_event_cannot_reintroduce_deleted_account_identity():
    deleted_account = Account.objects.create_user("late-event@example.com")
    deleted_id = str(deleted_account.pk)
    deleted_account.delete()
    event = {
        "id": "rc-late-extended",
        "type": "SUBSCRIPTION_EXTENDED",
        "app_user_id": deleted_id,
        "aliases": [deleted_id],
        "entitlement_ids": None,
    }
    body = json.dumps({"api_version": "1.0", "event": event}).encode()

    response = Client().post(
        "/api/v2/billing/revenuecat-webhook",
        data=body,
        content_type="application/json",
        headers=signed_headers(body, int(time.time())),
    )

    record = RevenueCatEvent.objects.get()
    assert response.status_code == 200
    assert record.app_user_id == ""
    assert record.payload == {"redacted": True}
    assert deleted_id not in json.dumps(record.payload)
    assert record.processing_error == "non_snapshot_event_no_known_account"


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
@pytest.mark.parametrize("event_type", ["SUBSCRIPTION_EXTENDED", "REFUND_REVERSED"])
def test_entitlement_affecting_non_snapshot_events_reconcile_provider_state(event_type):
    account = Account.objects.create_user(f"{event_type.lower()}@example.com")
    body = event_body(
        account,
        event_id=f"rc-{event_type.lower()}",
        event_type=event_type,
    )

    with patch("billing.webhooks.reconcile_account") as reconcile:
        response = Client().post(
            "/api/v2/billing/revenuecat-webhook",
            data=body,
            content_type="application/json",
            headers=signed_headers(body, int(time.time())),
        )

    record = RevenueCatEvent.objects.get()
    assert response.status_code == 200
    reconcile.assert_called_once_with(account)
    assert record.app_user_id == str(account.pk)
    assert record.processing_error == "non_snapshot_reconciled"


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_expiration_refreshes_active_aggregate_instead_of_leaving_stale_access():
    account = Account.objects.create_user("aggregate-expiration@example.com")
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=True,
    )
    body = event_body(account, event_id="rc-aggregate-expiration", event_type="EXPIRATION")

    with patch("billing.revenuecat._request", return_value=(404, b"")):
        response = Client().post(
            "/api/v2/billing/revenuecat-webhook",
            data=body,
            content_type="application/json",
            headers=signed_headers(body, int(time.time())),
        )

    assert response.status_code == 200
    assert account_has_premium(account) is False
    assert RevenueCatEvent.objects.get().processing_error == "snapshot_reconciled"


@pytest.mark.django_db
@override_settings(
    REVENUECAT_WEBHOOK_AUTHORIZATION=AUTHORIZATION,
    REVENUECAT_WEBHOOK_SIGNING_SECRET=SIGNING_SECRET,
)
def test_first_seen_delayed_positive_event_cannot_override_newer_inactive_aggregate():
    account = Account.objects.create_user("delayed-first-snapshot@example.com")
    aggregate = AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=False,
    )
    old_provider_time = django_timezone.now() - timedelta(days=1)
    event = {
        "id": "rc-delayed-first-positive",
        "type": "INITIAL_PURCHASE",
        "appUserId": str(account.pk),
        "entitlementIds": ["premium"],
        "expirationAtMs": int((django_timezone.now() + timedelta(days=1)).timestamp() * 1000),
        "eventTimestampMs": int(old_provider_time.timestamp() * 1000),
        "environment": "SANDBOX",
    }
    body = json.dumps({"apiVersion": "1.0", "event": event}, separators=(",", ":")).encode()

    with patch("billing.revenuecat._request", return_value=(404, b"")):
        response = Client().post(
            "/api/v2/billing/revenuecat-webhook",
            data=body,
            content_type="application/json",
            headers=signed_headers(body, int(time.time())),
        )

    environment = AccountEntitlement.objects.get(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
    )
    aggregate.refresh_from_db()
    assert response.status_code == 200
    assert environment.is_active is True
    assert environment.authority_observed_at <= aggregate.authority_observed_at
    assert aggregate.is_active is False
    assert account_has_premium(account) is False
    assert RevenueCatEvent.objects.get().processing_error == "snapshot_reconciled"
