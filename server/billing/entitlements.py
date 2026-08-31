from django.utils import timezone
from product.models import AccountEntitlement


def entitlement_is_active(entitlement, *, now=None):
    now = now or timezone.now()
    return entitlement.is_active and (
        entitlement.expires_at is None or entitlement.expires_at > now
    )


def account_has_premium(account, *, now=None):
    entitlement = AccountEntitlement.objects.filter(account=account).first()
    return bool(entitlement and entitlement_is_active(entitlement, now=now))
