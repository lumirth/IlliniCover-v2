from datetime import timedelta

from covers.models import ShadowCoverPrediction
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from identity.models import (
    AccountDeletionReceipt,
    AllauthRateLimitCache,
    IdentityRateBucket,
    SessionTokenVerifier,
)
from identity.services import cleanup_abandoned_unverified_accounts
from submissions.models import SubmissionRateBucket

from operations.jobs import JobAlreadyRunning, managed_job

SHADOW_PREDICTION_RETENTION = timedelta(days=30)


class Command(BaseCommand):
    help = "Idempotently clear expired sessions and rate-limit cache rows."

    def handle(self, *args, **options):
        try:
            with managed_job("cleanup") as run:
                now = timezone.now()
                expired_session_keys = Session.objects.filter(expire_date__lt=now).values(
                    "session_key"
                )
                expired_sessions = expired_session_keys.count()
                expired_verifiers, _ = SessionTokenVerifier.objects.filter(
                    Q(revoked_at__isnull=False) | Q(session_key__in=expired_session_keys)
                ).delete()
                Session.objects.filter(expire_date__lt=now).delete()
                orphaned_verifiers, _ = SessionTokenVerifier.objects.exclude(
                    session_key__in=Session.objects.values("session_key")
                ).delete()
                expired_cache, _ = AllauthRateLimitCache.objects.filter(expires__lt=now).delete()
                expired_submission_limits, _ = SubmissionRateBucket.objects.filter(
                    expires_at__lt=now
                ).delete()
                expired_identity_limits, _ = IdentityRateBucket.objects.filter(
                    expires_at__lt=now
                ).delete()
                expired_deletion_receipts, _ = AccountDeletionReceipt.objects.filter(
                    expires_at__lte=now
                ).delete()
                expired_shadow_predictions, _ = ShadowCoverPrediction.objects.filter(
                    created_at__lt=now - SHADOW_PREDICTION_RETENTION
                ).delete()
                abandoned_accounts = cleanup_abandoned_unverified_accounts(now=now)
                run.result_summary = {
                    "expiredSessionsDeleted": expired_sessions,
                    "sessionTokenVerifiersDeleted": expired_verifiers + orphaned_verifiers,
                    "expiredRateLimitRowsDeleted": (
                        expired_cache + expired_submission_limits + expired_identity_limits
                    ),
                    "expiredAccountDeletionReceiptsDeleted": expired_deletion_receipts,
                    "expiredShadowPredictionsDeleted": expired_shadow_predictions,
                    "abandonedUnverifiedAccountsDeleted": abandoned_accounts,
                }
        except JobAlreadyRunning:
            self.stdout.write("cleanup is already running")
            return
        self.stdout.write(self.style.SUCCESS("cleanup completed"))
