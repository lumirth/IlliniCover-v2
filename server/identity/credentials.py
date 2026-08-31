import hashlib
import hmac

from django.conf import settings
from product.models import InstallationActor

INSTALLATION_TOKEN_PREFIX = "ic_install_"


def installation_verifier(raw_token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"installation\0{raw_token}".encode(), hashlib.sha256
    ).hexdigest()


def lookup_installation(raw_token: str, *, for_update: bool = False) -> InstallationActor | None:
    verifier = installation_verifier(raw_token)
    query = (
        InstallationActor.objects.select_for_update() if for_update else InstallationActor.objects
    )
    actor = query.filter(verifier=verifier).first()
    return actor if actor is not None and actor.matches(verifier) else None


def authenticate_installation(raw_token: str) -> InstallationActor | None:
    return lookup_installation(raw_token)
