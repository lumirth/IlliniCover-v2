from django.core.management.base import BaseCommand, CommandError
from identity.models import Account
from operations.jobs import JobAlreadyRunning, managed_job

from billing.models import ProviderDeletionRequest
from billing.revenuecat import RevenueCatRequestError, process_deletion, reconcile_account


class Command(BaseCommand):
    help = "Reconcile local entitlements and retry durable RevenueCat customer deletions."

    def handle(self, *args, **options):
        try:
            with managed_job("reconcile_revenuecat") as run:
                reconciled = failed = deleted = 0
                for account in Account.objects.filter(is_active=True).iterator():
                    try:
                        reconcile_account(account)
                    except RevenueCatRequestError:
                        failed += 1
                    else:
                        reconciled += 1
                for deletion in ProviderDeletionRequest.objects.exclude(
                    status=ProviderDeletionRequest.Status.SUCCEEDED
                ).iterator():
                    try:
                        completed = process_deletion(deletion)
                    except RevenueCatRequestError:
                        failed += 1
                    else:
                        if not completed:
                            continue
                        deleted += 1
                run.result_summary = {
                    "accountsReconciled": reconciled,
                    "providerDeletionsCompleted": deleted,
                    "failures": failed,
                }
                if failed:
                    raise CommandError(f"RevenueCat reconciliation had {failed} failure(s)")
        except JobAlreadyRunning:
            self.stdout.write("reconcile_revenuecat is already running")
            return
        self.stdout.write(self.style.SUCCESS("RevenueCat reconciliation completed"))
