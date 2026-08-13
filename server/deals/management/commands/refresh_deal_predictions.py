from datetime import date

from covers.services import service_date_for
from django.core.management.base import BaseCommand
from operations.jobs import JobAlreadyRunning, managed_job

from deals.predictor import materialize_predictions, prediction_receipt_hash


class Command(BaseCommand):
    help = "Materialize the selected, receipt-backed deal recurrence baseline."

    def add_arguments(self, parser):
        parser.add_argument("--service-date", type=date.fromisoformat)

    def handle(self, *args, **options):
        from django.utils import timezone

        service_date = options["service_date"] or service_date_for(timezone.now())
        try:
            with managed_job("refresh_deal_predictions") as run:
                release, created = materialize_predictions(service_date)
                run.result_summary = {
                    "serviceDate": service_date.isoformat(),
                    "releaseId": str(release.id),
                    "predictionsCreated": created,
                    "selectionReceiptSha256": prediction_receipt_hash(),
                }
        except JobAlreadyRunning:
            self.stdout.write("refresh_deal_predictions is already running")
            return
        self.stdout.write(self.style.SUCCESS(f"{created} predictions materialized"))
