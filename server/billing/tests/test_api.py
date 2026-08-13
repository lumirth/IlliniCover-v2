from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.utils import timezone
from identity.models import Account
from identity.tokens import issue_session_token

from billing.entitlements import account_has_premium
from billing.models import AccountEntitlement


def authenticated_client(account: Account) -> Client:
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    return Client(headers={"X-Session-Token": issue_session_token(session)})


@pytest.mark.django_db
def test_public_access_aggregates_distinguishable_sandbox_and_production_rows():
    account = Account.objects.create_user("aggregate-access@example.com")
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PRODUCTION,
        is_active=False,
    )

    response = authenticated_client(account).get("/api/v2/me/entitlements")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["entitlements"][0]["isActive"] is True
    assert account_has_premium(account) is True
    assert set(
        AccountEntitlement.objects.filter(account=account).values_list("environment", flat=True)
    ) == {"sandbox", "production"}


@pytest.mark.django_db
def test_public_access_uses_newest_authoritative_provider_view():
    account = Account.objects.create_user("authoritative-access@example.com")
    now = timezone.now()
    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.SANDBOX,
        is_active=True,
        provider_updated_at=now - timedelta(hours=1),
    )
    aggregate = AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PROVIDER_AGGREGATE,
        is_active=False,
        provider_updated_at=now,
    )

    revoked = authenticated_client(account).get("/api/v2/me/entitlements")

    assert revoked.status_code == 200
    assert revoked.json()["entitlements"][0]["isActive"] is False
    assert account_has_premium(account) is False

    AccountEntitlement.objects.create(
        account=account,
        environment=AccountEntitlement.Environment.PRODUCTION,
        is_active=True,
        provider_updated_at=now + timedelta(minutes=1),
    )
    aggregate.refresh_from_db()

    renewed = authenticated_client(account).get("/api/v2/me/entitlements")

    assert renewed.status_code == 200
    assert renewed.json()["entitlements"][0]["isActive"] is True
    assert account_has_premium(account) is True


@pytest.mark.django_db
def test_public_access_applies_environment_events_only_after_aggregate_watermark():
    account = Account.objects.create_user("api-watermark@example.com")
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

    response = authenticated_client(account).get("/api/v2/me/entitlements")

    assert response.status_code == 200
    assert response.json()["entitlements"][0]["isActive"] is False
    assert account_has_premium(account) is False
