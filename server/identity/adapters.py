from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from config.network import keyed_client_identity
from django.db import transaction
from django.http import HttpResponseForbidden

from identity.tokens import revoke_session_token


class IlliniCoverAccountAdapter(DefaultAccountAdapter):
    def get_client_ip(self, request) -> str:
        # allauth uses this value as its per-IP cache identity. A keyed digest
        # preserves distinct network throttles without persisting raw addresses.
        return keyed_client_identity(request)

    def pre_login(self, request, user, **kwargs):
        if not request.path.startswith("/_allauth/") and not user.is_staff:
            raise ImmediateHttpResponse(HttpResponseForbidden())
        return super().pre_login(request, user, **kwargs)

    @transaction.atomic
    def logout(self, request) -> None:
        raw_token = request.headers.get("X-Session-Token", "")
        if raw_token:
            revoke_session_token(raw_token)
        super().logout(request)
