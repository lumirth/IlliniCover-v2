import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.test import Client
from django.utils import timezone

from identity.models import Account, SessionTokenVerifier


@pytest.mark.django_db
def test_existing_account_email_code_flow_rotates_verifier_only_session_token():
    Account.objects.create_user("person@example.com")
    account = Account.objects.get(email="person@example.com")
    EmailAddress.objects.create(
        user=account, email="person@example.com", verified=True, primary=True
    )
    client = Client()

    requested = client.post(
        "/_allauth/app/v1/auth/code/request",
        data={"email": "person@example.com"},
        content_type="application/json",
    )

    assert requested.status_code == 401
    pending_token = requested.json()["meta"]["session_token"]
    assert pending_token.startswith("ic_session_")
    assert pending_token not in SessionTokenVerifier.objects.get().verifier
    pending_verifier = SessionTokenVerifier.objects.get()
    assert pending_verifier.account_id is None
    pending_session = SessionStore(session_key=pending_verifier.session_key)
    remaining_seconds = (pending_session.get_expiry_date() - timezone.now()).total_seconds()
    assert 290 <= remaining_seconds <= 300
    assert {"id": "login_by_code", "is_pending": True} in requested.json()["data"]["flows"]
    code = re.search(
        r"\b([BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4})\b", mail.outbox[0].body
    ).group(1)

    confirmed = client.post(
        "/_allauth/app/v1/auth/code/confirm",
        data={"code": code},
        content_type="application/json",
        headers={"X-Session-Token": pending_token},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["meta"]["is_authenticated"] is True
    authenticated_token = confirmed.json()["meta"]["session_token"]
    assert authenticated_token != pending_token
    assert SessionTokenVerifier.objects.filter(revoked_at__isnull=False).count() == 1
    assert confirmed.json()["data"]["user"]["id"]


@pytest.mark.django_db
def test_passwordless_signup_requires_email_code_before_session_is_authenticated():
    client = Client()

    signup = client.post(
        "/_allauth/app/v1/auth/signup",
        data={"email": "new@example.com"},
        content_type="application/json",
    )

    assert signup.status_code == 401
    pending_token = signup.json()["meta"]["session_token"]
    assert any(
        flow == {"id": "verify_email", "is_pending": True}
        for flow in signup.json()["data"]["flows"]
    )
    code = re.search(
        r"\b([BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4})\b", mail.outbox[0].body
    ).group(1)

    verified = client.post(
        "/_allauth/app/v1/auth/email/verify",
        data={"key": code},
        content_type="application/json",
        headers={"X-Session-Token": pending_token},
    )

    assert verified.status_code == 200
    assert verified.json()["meta"]["is_authenticated"] is True
    assert verified.json()["data"]["user"]["email"] == "new@example.com"
    assert Account.objects.get(email="new@example.com").has_usable_password() is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("request_path", "resend_path", "email"),
    [
        (
            "/_allauth/app/v1/auth/code/request",
            "/_allauth/app/v1/auth/code/resend",
            "existing@example.com",
        ),
        (
            "/_allauth/app/v1/auth/signup",
            "/_allauth/app/v1/auth/email/verify/resend",
            "new@example.com",
        ),
    ],
)
def test_email_code_resend_is_available_but_bounded(request_path, resend_path, email):
    if request_path.endswith("code/request"):
        account = Account.objects.create_user(email)
        EmailAddress.objects.create(user=account, email=email, verified=True, primary=True)
    client = Client()
    requested = client.post(
        request_path,
        data={"email": email},
        content_type="application/json",
    )
    pending_token = requested.json()["meta"]["session_token"]

    statuses = []
    for _ in range(3):
        response = client.post(resend_path, headers={"X-Session-Token": pending_token})
        statuses.append(response.status_code)
        pending_token = response.json().get("meta", {}).get("session_token", pending_token)

    assert statuses == [200, 200, 409]
    assert len(mail.outbox) == 3


@pytest.mark.django_db
def test_logout_revokes_session_token_without_waiting_for_replay():
    account = Account.objects.create_user("person@example.com")
    EmailAddress.objects.create(
        user=account, email="person@example.com", verified=True, primary=True
    )
    client = Client()
    requested = client.post(
        "/_allauth/app/v1/auth/code/request",
        data={"email": "person@example.com"},
        content_type="application/json",
    )
    pending = requested.json()["meta"]["session_token"]
    code = re.search(
        r"\b([BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4})\b", mail.outbox[0].body
    ).group(1)
    confirmed = client.post(
        "/_allauth/app/v1/auth/code/confirm",
        data={"code": code},
        content_type="application/json",
        headers={"X-Session-Token": pending},
    )
    authenticated = confirmed.json()["meta"]["session_token"]

    response = client.delete(
        "/_allauth/app/v1/auth/session", headers={"X-Session-Token": authenticated}
    )

    assert response.status_code == 401
    assert SessionTokenVerifier.objects.filter(revoked_at__isnull=False).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path,payload",
    [
        ("/_allauth/app/v1/auth/login", {"email": "person@example.com", "password": "x"}),
        ("/_allauth/app/v1/auth/password/request", {"email": "person@example.com"}),
        ("/_allauth/app/v1/auth/password/reset", {"key": "x", "password": "new-password"}),
        ("/_allauth/app/v1/account/password/change", {"newPassword": "new-password"}),
    ],
)
def test_public_headless_password_credentials_are_not_routed(path, payload):
    account = Account.objects.create_user("person@example.com")

    response = Client().post(path, data=payload, content_type="application/json")

    assert response.status_code == 404
    account.refresh_from_db()
    assert account.has_usable_password() is False
