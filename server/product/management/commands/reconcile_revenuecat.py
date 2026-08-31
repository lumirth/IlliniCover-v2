from billing.revenuecat import RevenueCatRequestError, process_deletion, reconcile_account
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from product.models import (
    Account,
    AllauthRateLimitCache,
    ProviderDeletionRequest,
    RateBucket,
    SessionTokenVerifier,
)


class Command(BaseCommand):
    help = "Reconcile RevenueCat entitlements and pending account erasures."

    def handle(self, **options):
        failures = 0
        for account in Account.objects.iterator():
            try:
                reconcile_account(account)
            except RevenueCatRequestError:
                failures += 1
        for deletion in ProviderDeletionRequest.objects.iterator():
            if not process_deletion(deletion):
                failures += 1
        now = timezone.now()
        expired = Session.objects.filter(expire_date__lte=now)
        SessionTokenVerifier.objects.filter(session_key__in=expired.values("session_key")).delete()
        expired.delete()
        SessionTokenVerifier.objects.exclude(
            session_key__in=Session.objects.values("session_key")
        ).delete()
        AllauthRateLimitCache.objects.filter(expires__lte=now).delete()
        RateBucket.objects.filter(expires_at__lte=now).delete()
        if failures:
            raise CommandError(f"RevenueCat reconciliation left {failures} item(s) pending")
