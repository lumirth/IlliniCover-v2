import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from identity.models import InstallationActor, InstallationCredential

INSTALLATION_TOKEN_PREFIX = "ic_install_"


def installation_verifier(raw_token: str) -> str:
    return hmac.new(
        settings.INSTALLATION_TOKEN_PEPPER.encode(), raw_token.encode(), hashlib.sha256
    ).hexdigest()


@transaction.atomic
def issue_installation(raw_token: str) -> InstallationActor:
    actor = InstallationActor.objects.create()
    InstallationCredential.objects.create(actor=actor, verifier=installation_verifier(raw_token))
    return actor


def authenticate_installation(raw_token: str) -> InstallationActor | None:
    credential = lookup_installation_credential(raw_token)
    if credential is None:
        return None
    now = timezone.now()
    InstallationCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
    InstallationActor.objects.filter(pk=credential.actor_id).update(last_seen_at=now)
    return credential.actor


def lookup_installation_credential(raw_token: str) -> InstallationCredential | None:
    """Verify an active credential without recording an activity timestamp."""

    candidate = installation_verifier(raw_token)
    credential = active_credential(raw_token)
    if credential is None or not credential.matches(candidate):
        return None
    return credential


def active_credential(
    raw_token: str, *, for_update: bool = False
) -> InstallationCredential | None:
    query = InstallationCredential.objects.select_related("actor")
    if for_update:
        query = query.select_for_update()
    return query.filter(
        verifier=installation_verifier(raw_token),
        revoked_at__isnull=True,
    ).first()
