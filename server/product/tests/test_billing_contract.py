import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from billing.entitlements import account_has_premium
from billing.revenuecat import RevenueCatRequestError
from billing.schemas import RevenueCatEnvelopeSchema
from billing.webhooks import accept_revenuecat_event, verify_revenuecat_signature
from config.api import api

from product.models import Account, AccountEntitlement, RevenueCatEvent


def signature(payload, secret, timestamp):
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def envelope(account, event_id="event-1"):
    return RevenueCatEnvelopeSchema.model_validate(
        {
            "event": {
                "id": event_id,
                "type": "RENEWAL",
                "appUserId": str(account.pk),
            }
        }
    )


def test_webhook_signature_authenticates_body_and_timestamp():
    now, payload, secret = int(time.time()), b"{}", "secret"
    assert verify_revenuecat_signature(payload, signature(payload, secret, now), secret, now=now)
    assert not verify_revenuecat_signature(
        b"changed", signature(payload, secret, now), secret, now=now
    )
    assert not verify_revenuecat_signature(
        payload, signature(payload, secret, now - 301), secret, now=now
    )


@pytest.mark.django_db
def test_webhook_replay_is_idempotent_and_entitlement_expires(monkeypatch):
    account = Account.objects.create_user("blue@example.com")
    body = json.dumps(
        {
            "active_entitlements": {
                "items": [{"entitlement_id": "entlb2319dd271", "expires_at": None}]
            }
        }
    ).encode()
    monkeypatch.setattr("billing.revenuecat._request", lambda method, customer: (200, body))
    event, duplicate = accept_revenuecat_event(envelope(account))
    assert not duplicate and account_has_premium(account)
    assert accept_revenuecat_event(envelope(account))[1]
    assert RevenueCatEvent.objects.count() == 1
    entitlement = AccountEntitlement.objects.get(account=account)
    entitlement.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    entitlement.save()
    assert not account_has_premium(account)


@pytest.mark.django_db
def test_provider_outage_keeps_event_retryable(monkeypatch):
    account = Account.objects.create_user("retry@example.com")
    monkeypatch.setattr(
        "billing.revenuecat._request",
        lambda method, customer: (_ for _ in ()).throw(RevenueCatRequestError("offline")),
    )
    with pytest.raises(RevenueCatRequestError):
        accept_revenuecat_event(envelope(account, "retry-event"))
    assert not RevenueCatEvent.objects.filter(pk="retry-event").exists()

    monkeypatch.setattr("billing.revenuecat._request", lambda method, customer: (404, b""))
    record, duplicate = accept_revenuecat_event(envelope(account, "retry-event"))
    assert record.pk == "retry-event" and not duplicate


@pytest.mark.django_db
def test_contract_is_unversioned_camel_case_and_has_no_internal_ids():
    schema = api.get_openapi_schema(path_prefix="/api")
    encoded = json.dumps(schema)
    assert "/api/status" in schema["paths"] and "/api/v2" not in encoded
    for path, method in (
        ("/api/me", "get"),
        ("/api/me", "delete"),
        ("/api/me/link-installation", "post"),
        ("/api/me/entitlements", "get"),
        ("/api/venues/{venue}/cover/time-machine", "get"),
    ):
        assert 401 in schema["paths"][path][method]["responses"]
    for removed in (
        "decisionId",
        "predictionId",
        "eventId",
        "account-deletions",
        "installations/current",
    ):
        assert removed not in encoded
