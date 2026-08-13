import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore

from identity.credentials import authenticate_installation, issue_installation
from identity.models import Account, InstallationCredential, SessionTokenVerifier
from identity.tokens import (
    issue_session_token,
    lookup_session_token,
    revoke_session_token,
    rotate_session_token,
)


@pytest.mark.django_db
def test_client_installation_token_is_never_stored_raw():
    raw_token = "ic_install_" + "a" * 43
    actor = issue_installation(raw_token)

    stored = InstallationCredential.objects.get(actor=actor)

    assert raw_token.startswith("ic_install_")
    assert raw_token not in stored.verifier
    assert len(stored.verifier) == 64
    assert authenticate_installation(raw_token) == actor


@pytest.mark.django_db
def test_session_token_rotation_revokes_the_old_token_and_replay_fails():
    account = Account.objects.create_user("person@example.com")
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    original = issue_session_token(session)

    rotated = rotate_session_token(original)

    assert rotated is not None and rotated != original
    assert lookup_session_token(original) is None
    assert lookup_session_token(rotated) is not None
    assert SessionTokenVerifier.objects.filter(revoked_at__isnull=False).count() == 1


@pytest.mark.django_db
def test_revoked_session_token_cannot_be_replayed_and_raw_token_is_never_stored():
    session = SessionStore()
    session["purpose"] = "test"
    session.save()
    raw_token = issue_session_token(session)

    assert raw_token not in SessionTokenVerifier.objects.get().verifier
    assert revoke_session_token(raw_token) is True
    assert revoke_session_token(raw_token) is False
    assert lookup_session_token(raw_token) is None
