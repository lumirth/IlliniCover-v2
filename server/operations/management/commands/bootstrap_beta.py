from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.core.management.base import BaseCommand
from handbook.models import HandbookPage

from operations.jobs import JobAlreadyRunning, managed_job


class Command(BaseCommand):
    help = "Idempotently import checked beta datasets and seed required reference rows."

    def handle(self, *args, **options):
        try:
            with managed_job("bootstrap_beta") as run:
                call_command("import_venues", verbosity=0)
                call_command("import_cover_dataset", verbosity=0)
                from covers.releases import build_and_promote_initial_release

                cover_release = build_and_promote_initial_release()
                call_command("import_deal_dataset", verbosity=0)
                from covers.services import service_date_for
                from deals.models import DealPredictionRelease
                from deals.predictor import (
                    build_selected_prediction_release,
                    materialize_predictions,
                    promote_prediction_release,
                )
                from django.utils import timezone

                current_deal_release = DealPredictionRelease.objects.filter(
                    is_authoritative=True
                ).first()
                if current_deal_release is None:
                    current_deal_release = promote_prediction_release(
                        build_selected_prediction_release()
                    )
                release, predictions_created = materialize_predictions(
                    service_date_for(timezone.now())
                )
                site_host = urlparse(settings.PUBLIC_API_ORIGIN).hostname
                if not site_host:
                    raise ValueError("PUBLIC_API_ORIGIN must contain a hostname")
                Site.objects.update_or_create(
                    pk=1,
                    defaults={"domain": site_host, "name": "IlliniCover"},
                )
                HandbookPage.objects.get_or_create(
                    slug="about-cover",
                    defaults={
                        "title": "Understanding cover",
                        "summary": "How IlliniCover reports live and historical cover estimates.",
                        "body_markdown": (
                            "IlliniCover combines community reports with historical patterns. "
                            "A displayed estimate is not an official venue price."
                        ),
                        "status": HandbookPage.Status.PUBLISHED,
                        "sort_order": 10,
                    },
                )
                run.result_summary = {
                    "venues": True,
                    "coverDataset": True,
                    "coverModelRelease": str(cover_release.id),
                    "dealDataset": True,
                    "dealPredictionRelease": str(release.id),
                    "dealPredictionsCreated": predictions_created,
                    "referenceContent": True,
                }
        except JobAlreadyRunning:
            self.stdout.write("bootstrap_beta is already running")
            return
        self.stdout.write(self.style.SUCCESS("beta bootstrap completed"))
