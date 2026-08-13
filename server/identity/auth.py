from django.contrib.auth import SESSION_KEY
from ninja.security import APIKeyHeader

from identity.credentials import authenticate_installation, lookup_installation_credential
from identity.models import Account
from identity.tokens import lookup_session_token


class InstallationTokenAuth(APIKeyHeader):
    param_name = "X-Installation-Token"

    def __init__(self, *, record_activity: bool = True):
        self.record_activity = record_activity
        super().__init__()

    def authenticate(self, request, key):
        if self.record_activity:
            return authenticate_installation(key)
        credential = lookup_installation_credential(key)
        return credential.actor if credential is not None else None


class SessionTokenAuth(APIKeyHeader):
    param_name = "X-Session-Token"

    def authenticate(self, request, key):
        session = lookup_session_token(key)
        if session is None:
            return None
        account_id = session.get(SESSION_KEY)
        if not account_id:
            return None
        return Account.objects.filter(pk=account_id, is_active=True).first()


installation_auth = InstallationTokenAuth()
read_only_installation_auth = InstallationTokenAuth(record_activity=False)
session_auth = SessionTokenAuth()
