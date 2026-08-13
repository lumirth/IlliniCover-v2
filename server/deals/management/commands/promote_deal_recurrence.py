from datetime import date

from covers.services import service_date_for
from django.core.management.base import BaseCommand
from django.utils import timezone
from operations.jobs import JobAlreadyRunning, managed_job

from deals.predictor import (
    build_selected_prediction_release,
    materialize_predictions,
    prediction_receipt_hash,
    promote_prediction_release,
)


class Command(BaseCommand):
    help = "Explicitly promote the checked deal recurrence release and materialize a slate."

    def add_arguments(self, parser):
        parser.add_argument("--service-date", type=date.fromisoformat)

    def handle(self, *args, **options):
        service_date = options["service_date"] or service_date_for(timezone.now())
        try:
            with managed_job("promote_deal_recurrence") as run:
                release = promote_prediction_release(build_selected_prediction_release())
                selected, created = materialize_predictions(service_date)
                if selected.pk != release.pk:
                    raise RuntimeError("Materialization did not use the promoted deal release")
                run.result_summary = {
                    "serviceDate": service_date.isoformat(),
                    "releaseId": str(release.id),
                    "predictionsCreated": created,
                    "selectionReceiptSha256": prediction_receipt_hash(),
                }
        except JobAlreadyRunning:
            self.stdout.write("promote_deal_recurrence is already running")
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"promoted {release.predictor_version}; {created} predictions materialized"
            )
        )
