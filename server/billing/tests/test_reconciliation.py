import json
from datetime import timedelta
from unittest.mock import call, patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from identity.models import Account

from billing.entitlements import account_has_premium
from billing.models import AccountEntitlement, ProviderDeletionRequest
from billing.revenuecat import _store_provider_aggregate, process_deletion, reconcile_account


@pytest.mark.django_db
@override_settings(
    REVENUECAT_SECRET_API_KEY="scoped-test-key",
    REVENUECAT_PROJECT_ID="proj72780529",
    REVENUECAT_PREMIUM_ENTITLEMENT_RESOURCE_ID="entlb2319dd271",
)
def test_v2_reconciliation_mirrors_active_entitlement_milliseconds():
    account = Account.objects.create_user("premium@example.com")
    expiration_ms = int((timezone.now().timestamp() + 3600) * 1000)
    body = json.dumps(
        {
            "active_entitlements": {
                "items": [{"entitlement_id": "entlb2319dd271", "expires_at": expiration_ms}]
            }
        }
    ).encode()

    with patch("billing.revenuecat._request", return_value=(200, body)):
        reconcile_account(account)

    mirror = AccountEntitlement.objects.get(account=account)
    assert mirror.is_active is True
    assert int(mirror.expires_at.timestamp() * 1000) == expiration_ms


@pytest.mark.django_db
def test_v2_reconciliation_404_revokes_local_access():
    account = Account.objects.create_user("missing@example.com")
    AccountEntitlement.objects.create(account=account, is_active=True)

    with patch("billing.revenuecat._request", return_value=(404, b"")):
        reconcile_account(account)

    assert AccountEntitlement.objects.get(account=account).is_active is False


@pytest.mark.django_db
def test_reconciliation_supersedes_stale_active_environment_row():
    account = Account.objects.create_user("stale-environment@example.com")
    stale = AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        provider_updated_at=timezone.now() - timedelta(hours=1),
    )

    with patch("billing.revenuecat._request", return_value=(404, b"")):
        reconcile_account(account)

    stale.refresh_from_db()
    assert stale.is_active is True
    assert account_has_premium(account) is False


@pytest.mark.django_db
def test_newer_webhook_environment_row_supersedes_older_reconciliation_snapshot():
    account = Account.objects.create_user("newer-webhook@example.com")
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=False,
        provider_updated_at=timezone.now() - timedelta(minutes=5),
    )
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PRODUCTION,
        is_active=True,
        provider_updated_at=timezone.now(),
    )

    assert account_has_premium(account) is True


@pytest.mark.django_db
def test_newer_inactive_environment_event_does_not_resurrect_pre_snapshot_access():
    account = Account.objects.create_user("snapshot-watermark@example.com")
    now = timezone.now()
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        provider_updated_at=now - timedelta(hours=1),
    )
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=False,
        provider_updated_at=now,
    )
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PRODUCTION,
        is_active=False,
        provider_updated_at=now + timedelta(minutes=1),
    )

    assert account_has_premium(account) is False


@pytest.mark.django_db
def test_webhook_mirrored_during_reconciliation_remains_newer_than_snapshot():
    account = Account.objects.create_user("reconciliation-race@example.com")
    snapshot_started = timezone.now() - timedelta(minutes=2)
    webhook_event_at = snapshot_started + timedelta(minutes=1)
    local_write_would_be = snapshot_started + timedelta(minutes=2)

    def provider_request(_method, _app_user_id):
        AccountEntitlement.objects.create(
            account=account,
            environment=AccountEntitlement.Environment.PRODUCTION,
            is_active=True,
            provider_updated_at=webhook_event_at,
            authority_observed_at=webhook_event_at,
        )
        return 404, b""

    with (
        patch("billing.revenuecat._request", side_effect=provider_request),
        patch(
            "billing.revenuecat.timezone.now",
            side_effect=[snapshot_started, *([local_write_would_be] * 10)],
        ),
    ):
        reconcile_account(account)

    aggregate = AccountEntitlement.objects.get(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
    )
    assert aggregate.authority_observed_at == snapshot_started
    assert account_has_premium(account) is True


@pytest.mark.django_db
def test_provider_clock_skew_cannot_hide_webhook_received_during_snapshot():
    account = Account.objects.create_user("reconciliation-skew@example.com")
    snapshot_started = timezone.now()
    received_during_request = snapshot_started + timedelta(seconds=1)
    provider_clock_behind = snapshot_started - timedelta(hours=2)

    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=False,
        provider_updated_at=snapshot_started,
        authority_observed_at=snapshot_started,
    )
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        provider_updated_at=provider_clock_behind,
        authority_observed_at=received_during_request,
    )

    assert account_has_premium(account) is True


@pytest.mark.django_db
def test_slower_older_reconciliation_cannot_overwrite_newer_provider_snapshot():
    account = Account.objects.create_user("reconciliation-order@example.com")
    older_started = timezone.now() - timedelta(seconds=2)
    newer_started = timezone.now() - timedelta(seconds=1)

    assert _store_provider_aggregate(
        account,
        snapshot_started_at=newer_started,
        is_active=False,
        expires_at=None,
    ) is True
    assert _store_provider_aggregate(
        account,
        snapshot_started_at=older_started,
        is_active=True,
        expires_at=timezone.now() + timedelta(days=1),
    ) is False

    aggregate = AccountEntitlement.objects.get(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
    )
    assert aggregate.authority_observed_at == newer_started
    assert aggregate.is_active is False
    assert account_has_premium(account) is False


@pytest.mark.django_db
def test_v2_queued_customer_deletion_remains_durable_until_provider_confirms_absence():
    deletion = ProviderDeletionRequest.objects.create(provider_customer_id="account-uuid")

    with patch(
        "billing.revenuecat._request",
        side_effect=[(202, b""), (200, b"{}"), (404, b"")],
    ) as request:
        assert process_deletion(deletion) is False
        deletion.refresh_from_db()
        assert deletion.status == ProviderDeletionRequest.Status.QUEUED
        assert deletion.attempts == 1

        assert process_deletion(deletion) is False
        deletion.refresh_from_db()
        assert deletion.status == ProviderDeletionRequest.Status.QUEUED
        assert deletion.attempts == 2

        assert process_deletion(deletion) is True

    assert not ProviderDeletionRequest.objects.filter(pk=deletion.pk).exists()
    assert request.call_args_list == [
        call("DELETE", "account-uuid"),
        call("GET", "account-uuid"),
        call("GET", "account-uuid"),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_status", [200, 404])
def test_v2_terminal_customer_deletion_removes_provider_identifier(terminal_status):
    deletion = ProviderDeletionRequest.objects.create(provider_customer_id="account-uuid")

    with patch("billing.revenuecat._request", return_value=(terminal_status, b"")):
        assert process_deletion(deletion) is True

    assert not ProviderDeletionRequest.objects.filter(pk=deletion.pk).exists()


@pytest.mark.django_db
def test_reconciliation_command_checks_accounts_without_an_existing_local_mirror(monkeypatch):
    account = Account.objects.create_user("missed-webhook@example.com")
    requested = []

    def record(account_to_reconcile):
        requested.append(account_to_reconcile.pk)

    monkeypatch.setattr(
        "billing.management.commands.reconcile_revenuecat.reconcile_account", record
    )

    call_command("reconcile_revenuecat")

    assert requested == [account.pk]
