import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import connection, connections
from identity.models import Account
from identity.services import delete_account

from billing.models import AccountEntitlement, RevenueCatEvent
from billing.revenuecat import reconcile_account
from billing.schemas import RevenueCatEnvelopeSchema
from billing.webhooks import accept_revenuecat_event


def _close_connections(worker):
    def wrapped(*args, **kwargs):
        connections.close_all()
        try:
            return worker(*args, **kwargs)
        finally:
            connections.close_all()

    return wrapped


def _snapshot(account: Account, event_id: str) -> RevenueCatEnvelopeSchema:
    return RevenueCatEnvelopeSchema.model_validate(
        {
            "apiVersion": "1.0",
            "event": {
                "id": event_id,
                "type": "INITIAL_PURCHASE",
                "appUserId": str(account.pk),
                "entitlementIds": ["premium"],
                "environment": "SANDBOX",
            },
        }
    )


@pytest.mark.django_db(transaction=True)
def test_same_account_provider_reads_are_serialized_before_observation():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance test")

    account = Account.objects.create_user("serialized-provider@example.com")
    first_entered = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    call_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    call_count = 0

    active_body = json.dumps(
        {
            "active_entitlements": {
                "items": [{"entitlement_id": "entlb2319dd271", "expires_at": None}]
            }
        }
    ).encode()
    inactive_body = json.dumps({"active_entitlements": {"items": []}}).encode()

    def provider_request(_method, _app_user_id):
        nonlocal active_calls, max_active_calls, call_count
        with call_lock:
            call_count += 1
            this_call = call_count
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            if this_call == 1:
                first_entered.set()
                assert second_started.wait(timeout=5)
                assert release_first.wait(timeout=5)
                return 200, active_body
            return 200, inactive_body
        finally:
            with call_lock:
                active_calls -= 1

    def run_reconciliation(*, mark_started=False):
        connections.close_all()
        if mark_started:
            second_started.set()
        reconcile_account(Account.objects.get(pk=account.pk))
        connections.close_all()

    with (
        patch("billing.revenuecat._request", side_effect=provider_request),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(run_reconciliation)
        assert first_entered.wait(timeout=5)
        second = executor.submit(run_reconciliation, mark_started=True)
        assert second_started.wait(timeout=5)
        # The second worker has reached reconcile_account but cannot enter the
        # provider read while the first account-row lock is held.
        assert call_count == 1
        release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)

    aggregate = AccountEntitlement.objects.get(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
    )
    assert call_count == 2
    assert max_active_calls == 1
    assert aggregate.is_active is False


@pytest.mark.django_db(transaction=True)
def test_webhook_that_wins_account_lock_is_removed_by_concurrent_deletion():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance test")

    account = Account.objects.create_user("webhook-first@example.com")
    envelope = _snapshot(account, "rc-webhook-first")
    webhook_holds_account = threading.Event()
    release_webhook = threading.Event()
    deletion_started = threading.Event()
    real_get_or_create = RevenueCatEvent.objects.get_or_create

    def paused_get_or_create(*args, **kwargs):
        webhook_holds_account.set()
        assert release_webhook.wait(timeout=10)
        return real_get_or_create(*args, **kwargs)

    @_close_connections
    def webhook_worker():
        return accept_revenuecat_event(envelope)

    @_close_connections
    def deletion_worker():
        deletion_started.set()
        return delete_account(
            Account.objects.get(pk=account.pk),
            request_id=uuid.uuid4(),
        )

    with (
        patch.object(
            RevenueCatEvent.objects,
            "get_or_create",
            side_effect=paused_get_or_create,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        accepted = executor.submit(webhook_worker)
        assert webhook_holds_account.wait(timeout=10)
        deleted = executor.submit(deletion_worker)
        assert deletion_started.wait(timeout=10)
        assert not deleted.done()
        release_webhook.set()
        accepted.result(timeout=10)
        deleted.result(timeout=10)

    assert not Account.objects.filter(pk=account.pk).exists()
    assert not RevenueCatEvent.objects.filter(provider_event_id="rc-webhook-first").exists()


@pytest.mark.django_db(transaction=True)
def test_webhook_after_deletion_lock_retains_no_deleted_account_identifier():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance test")

    account = Account.objects.create_user("deletion-first@example.com")
    account_id = str(account.pk)
    envelope = _snapshot(account, "rc-deletion-first")
    deletion_holds_account = threading.Event()
    release_deletion = threading.Event()
    webhook_reached_create = threading.Event()

    from identity.services import _account_bound_session_keys

    def paused_session_scan(locked_account):
        deletion_holds_account.set()
        assert release_deletion.wait(timeout=10)
        return _account_bound_session_keys(locked_account)

    real_get_or_create = RevenueCatEvent.objects.get_or_create

    def observed_get_or_create(*args, **kwargs):
        webhook_reached_create.set()
        return real_get_or_create(*args, **kwargs)

    @_close_connections
    def deletion_worker():
        return delete_account(
            Account.objects.get(pk=account.pk),
            request_id=uuid.uuid4(),
        )

    @_close_connections
    def webhook_worker():
        return accept_revenuecat_event(envelope)

    with (
        patch(
            "identity.services._account_bound_session_keys",
            side_effect=paused_session_scan,
        ),
        patch.object(
            RevenueCatEvent.objects,
            "get_or_create",
            side_effect=observed_get_or_create,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        deleted = executor.submit(deletion_worker)
        assert deletion_holds_account.wait(timeout=10)
        accepted = executor.submit(webhook_worker)
        assert not webhook_reached_create.wait(timeout=0.2)
        release_deletion.set()
        deleted.result(timeout=10)
        accepted.result(timeout=10)

    record = RevenueCatEvent.objects.get(provider_event_id="rc-deletion-first")
    assert not Account.objects.filter(pk=account.pk).exists()
    assert record.app_user_id == ""
    assert record.payload == {"redacted": True}
    assert account_id not in json.dumps(record.payload)
    assert record.processing_error == "account unavailable"
