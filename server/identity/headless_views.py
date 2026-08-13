from allauth.headless.account import views as account_views
from allauth.headless.base.response import AuthenticationResponse, UnauthorizedResponse
from django.db import transaction

from identity.models import Account
from identity.tokens import revoke_session_token


def _account_reference(value):
    if not isinstance(value, dict):
        return None
    for key, item in value.items():
        if key in {"user_pk", "user_id"} and item:
            return item
        found = _account_reference(item)
        if found:
            return found
    return None


class _PendingAccountLifecycleMixin:
    """Serialize pending challenge writes with account deletion."""

    @transaction.atomic
    def handle(self, request, *args, **kwargs):
        account_reference = None
        for key in ("account_login", "account_email_verification_code"):
            account_reference = _account_reference(request.session.get(key))
            if account_reference:
                break
        if account_reference:
            account = (
                Account.objects.select_for_update()
                .filter(pk=account_reference, is_active=True)
                .first()
            )
            if account is None:
                raw_token = request.headers.get("X-Session-Token", "")
                if raw_token:
                    revoke_session_token(raw_token)
                request.session.flush()
                return UnauthorizedResponse(request, status=410)
        return super().handle(request, *args, **kwargs)  # type: ignore[misc]


class LifecycleRequestLoginCodeView(account_views.RequestLoginCodeView):
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        candidate = self.input._user
        if candidate is not None:
            account = (
                Account.objects.select_for_update()
                .filter(pk=candidate.pk, is_active=True)
                .first()
            )
            if account is None:
                # The form resolved this account before a concurrent deletion
                # committed. Do not recreate its email challenge afterward.
                return AuthenticationResponse(request)
            self.input._user = account
        return super().post(request, *args, **kwargs)


class LifecycleResendLoginCodeView(
    _PendingAccountLifecycleMixin, account_views.ResendLoginCodeView
):
    pass


class LifecycleConfirmLoginCodeView(
    _PendingAccountLifecycleMixin, account_views.ConfirmLoginCodeView
):
    pass


class LifecycleVerifyEmailView(_PendingAccountLifecycleMixin, account_views.VerifyEmailView):
    pass


class LifecycleResendEmailVerificationCodeView(
    _PendingAccountLifecycleMixin,
    account_views.ResendEmailVerificationCodeView,
):
    pass
