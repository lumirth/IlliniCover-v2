import hashlib
import hmac
import secrets

from allauth.headless.internal import sessionkit
from allauth.headless.tokens.strategies.base import AbstractTokenStrategy
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest
from product.models import Account, SessionTokenVerifier

SESSION_TOKEN_PREFIX = "ic_session_"


def session_verifier(raw_token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"session\0{raw_token}".encode(), hashlib.sha256
    ).hexdigest()


def issue_session_token(session: SessionBase) -> str:
    account_id = session.get(SESSION_KEY)
    if not account_id and any(
        session.get(key) for key in ("account_login", "account_email_verification_code")
    ):
        session.set_expiry(settings.PENDING_EMAIL_AUTH_SESSION_TTL_SECONDS)
    if not session.session_key:
        session.save()
    session_key = session.session_key
    if not session_key:
        raise RuntimeError("Django did not persist the session")
    SessionTokenVerifier.objects.filter(session_key=session_key).delete()
    raw_token = SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    account = Account.objects.filter(pk=account_id).first() if account_id else None
    SessionTokenVerifier.objects.create(
        verifier=session_verifier(raw_token), session_key=session_key, account=account
    )
    return raw_token


def lookup_session_token(raw_token: str) -> SessionBase | None:
    candidate = session_verifier(raw_token)
    record = SessionTokenVerifier.objects.filter(verifier=candidate).first()
    if record is None or not record.matches(candidate):
        return None
    store = sessionkit.session_store(record.session_key)
    if not sessionkit.session_store().exists(record.session_key):
        record.delete()
        return None
    return store


def revoke_session_token(raw_token: str) -> bool:
    candidate = session_verifier(raw_token)
    record = SessionTokenVerifier.objects.filter(verifier=candidate).first()
    if record is None or not record.matches(candidate):
        return False
    record.delete()
    return True


def rotate_session_token(raw_token: str) -> str | None:
    session = lookup_session_token(raw_token)
    if session is None:
        return None
    revoke_session_token(raw_token)
    return issue_session_token(session)


class VerifierOnlySessionTokenStrategy(AbstractTokenStrategy):
    def create_session_token(self, request: HttpRequest) -> str:
        previous = self.get_session_token(request)
        if previous:
            revoke_session_token(previous)
        return issue_session_token(request.session)

    def lookup_session(self, session_token: str) -> SessionBase | None:
        return lookup_session_token(session_token)
