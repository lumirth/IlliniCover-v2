from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from operations.imports import import_run, jsonl_rows, open_release

from venues.models import Venue, VenueAlias

DEFAULT_RELEASE = settings.REPOSITORY_DIR / "data" / "venues" / "venues-v1"


class Command(BaseCommand):
    help = "Import a versioned venue release and record an import receipt."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default=str(DEFAULT_RELEASE / "manifest.json"))
        parser.add_argument("--dataset", default=str(DEFAULT_RELEASE / "venues-v1.jsonl"))

    @transaction.atomic
    def handle(self, *args, **options):
        release, dataset = open_release(options["manifest"], options["dataset"])
        with import_run(release) as run:
            for row in jsonl_rows(dataset):
                run.rows_seen += 1
                coordinates = row.get("coordinates") or {}
                venue, created = Venue.objects.update_or_create(
                    slug=row["venue_slug"],
                    defaults={
                        "name": row["display_name"],
                        "address": row.get("address", {}).get("display", ""),
                        "latitude": coordinates.get("latitude"),
                        "longitude": coordinates.get("longitude"),
                        "opened_year": row.get("opened_year"),
                        "is_active": row["active"],
                    },
                )
                for alias in row.get("aliases", []):
                    VenueAlias.objects.update_or_create(
                        alias=alias["value"],
                        defaults={"venue": venue, "source": alias.get("kind", "")},
                    )
                run.rows_accepted += int(created)
        self.stdout.write(
            self.style.SUCCESS(
                f"{release.name}: {run.rows_seen} rows checked, {run.rows_accepted} venues created"
            )
        )
