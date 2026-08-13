from django.conf import settings
from django.utils import timezone

from billing.models import AccountEntitlement


def entitlement_is_active(entitlement: AccountEntitlement, *, now=None) -> bool:
    """Compute access from both the provider mirror bit and its expiry boundary."""

    now = now or timezone.now()
    return (
        entitlement.entitlement_identifier == settings.REVENUECAT_PREMIUM_ENTITLEMENT
        and entitlement.is_active
        and (entitlement.expires_at is None or entitlement.expires_at > now)
    )


def authorization_entitlements(
    entitlements: list[AccountEntitlement],
) -> list[AccountEntitlement]:
    """Choose the newest authoritative RevenueCat view for access.

    Webhooks retain separate sandbox and production rows so operations can
    distinguish their origins. A successful provider reconciliation stores an
    aggregate snapshot across those environments. That snapshot must supersede
    older webhook rows or a missed revocation could leave premium enabled
    forever. A later webhook becomes authoritative again until the next
    reconciliation, preserving immediate purchase and renewal updates.
    """

    matching = [
        entitlement
        for entitlement in entitlements
        if entitlement.entitlement_identifier == settings.REVENUECAT_PREMIUM_ENTITLEMENT
    ]
    aggregate = next(
        (
            entitlement
            for entitlement in matching
            if entitlement.environment
            == AccountEntitlement.Environment.PROVIDER_AGGREGATE
        ),
        None,
    )
    environment_rows = [
        entitlement
        for entitlement in matching
        if entitlement.environment
        != AccountEntitlement.Environment.PROVIDER_AGGREGATE
    ]
    if aggregate is None:
        return environment_rows

    aggregate_at = aggregate.authority_observed_at
    newer_environment_rows = [
        entitlement
        for entitlement in environment_rows
        if entitlement.authority_observed_at > aggregate_at
    ]
    # The aggregate is a cross-environment watermark. Environment rows at or
    # before that watermark are already represented by it and must never be
    # resurrected merely because an unrelated environment later emits an
    # event. Newer rows overlay the snapshot so a purchase can grant access
    # immediately; an environment-specific revocation cannot prove that every
    # other store environment is inactive, so the aggregate remains until the
    # next provider reconciliation refreshes it.
    return [aggregate, *newer_environment_rows]


def account_has_premium(account, *, now=None) -> bool:
    # RevenueCat account access spans TestFlight sandbox and App Store
    # production purchases. Keep their rows distinguishable without requiring
    # a client-asserted distribution channel for authorization.
    entitlements = list(
        AccountEntitlement.objects.filter(
            account=account,
            entitlement_identifier=settings.REVENUECAT_PREMIUM_ENTITLEMENT,
        )
    )
    return any(
        entitlement_is_active(entitlement, now=now)
        for entitlement in authorization_entitlements(entitlements)
    )
