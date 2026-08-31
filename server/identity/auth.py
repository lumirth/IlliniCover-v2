from django.contrib.auth import SESSION_KEY
from ninja.security import APIKeyHeader
from product.models import Account

from identity.credentials import authenticate_installation, lookup_installation
from identity.tokens import lookup_session_token


class InstallationTokenAuth(APIKeyHeader):
    param_name = "X-Installation-Token"

    def __init__(self, *, record_activity=True):
        self.record_activity = record_activity
        super().__init__()

    def authenticate(self, request, key):
        return authenticate_installation(key) if self.record_activity else lookup_installation(key)


class SessionTokenAuth(APIKeyHeader):
    param_name = "X-Session-Token"

    def authenticate(self, request, key):
        session = lookup_session_token(key)
        account_id = session.get(SESSION_KEY) if session else None
        return Account.objects.filter(pk=account_id, is_active=True).first() if account_id else None


installation_auth = InstallationTokenAuth()
read_only_installation_auth = InstallationTokenAuth(record_activity=False)
session_auth = SessionTokenAuth()
