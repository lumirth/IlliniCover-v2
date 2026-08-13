"""Passwordless allauth Headless surface for the public mobile client."""

from allauth.headless.account import views as account_views
from allauth.headless.base import views as base_views
from allauth.headless.constants import Client
from allauth.headless.tokens import urls as token_urls
from django.db import transaction
from django.urls import include, path

from identity import headless_views


def atomic_app_view(view_class):
    # allauth's app_view authentication context explicitly saves the headless
    # DB session in its finally block. Wrapping that complete callable keeps
    # the account lifecycle lock until both the view and that session save
    # commit, without making unrelated public APIs transactional.
    return transaction.atomic(view_class.as_api_view(client=Client.APP))


app_patterns = [
    path("config", base_views.ConfigView.as_api_view(client=Client.APP), name="config"),
    path(
        "auth/session",
        atomic_app_view(account_views.SessionView),
        name="current_session",
    ),
    path(
        "auth/code/request",
        atomic_app_view(headless_views.LifecycleRequestLoginCodeView),
        name="request_login_code",
    ),
    path(
        "auth/code/resend",
        atomic_app_view(headless_views.LifecycleResendLoginCodeView),
        name="resend_login_code",
    ),
    path(
        "auth/code/confirm",
        atomic_app_view(headless_views.LifecycleConfirmLoginCodeView),
        name="confirm_login_code",
    ),
    path(
        "auth/signup",
        atomic_app_view(account_views.SignupView),
        name="signup",
    ),
    path(
        "auth/email/verify",
        atomic_app_view(headless_views.LifecycleVerifyEmailView),
        name="verify_email",
    ),
    path(
        "auth/email/verify/resend",
        atomic_app_view(headless_views.LifecycleResendEmailVerificationCodeView),
        name="resend_email_verification_code",
    ),
    path("", include((token_urls.build_urlpatterns(Client.APP), "headless_tokens"))),
]

urlpatterns = [path("app/v1/", include((app_patterns, "passwordless_headless")))]
