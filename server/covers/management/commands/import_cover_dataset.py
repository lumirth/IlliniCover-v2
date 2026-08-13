import hashlib
import json
import uuid
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from operations.imports import import_run, jsonl_rows, open_release
from submissions.models import Submission
from venues.models import Venue

from covers.models import CoverObservation

DEFAULT_RELEASE = settings.REPOSITORY_DIR / "data" / "cover" / "recovered-cover-v1"
IMPORT_NAMESPACE = uuid.UUID("15b702d2-da31-4011-ac18-b5e9f951e0ae")


class Command(BaseCommand):
    help = "Import immutable historical cover observations without creating live decisions."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default=str(DEFAULT_RELEASE / "manifest.json"))
        parser.add_argument(
            "--dataset", default=str(DEFAULT_RELEASE / "cover-observations-v1.jsonl")
        )

    @transaction.atomic
    def handle(self, *args, **options):
        release, dataset = open_release(options["manifest"], options["dataset"])
        venues = {venue.slug: venue for venue in Venue.objects.all()}
        with import_run(release) as run:
            for row in jsonl_rows(dataset):
                run.rows_seen += 1
                venue = venues.get(row["venue_slug"])
                if venue is None:
                    raise CommandError(f"Unknown venue {row['venue_slug']}; import venues first")
                source_key = row["source_record_key"]
                fingerprint = hashlib.sha256(
                    json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                submission_id = uuid.uuid5(IMPORT_NAMESPACE, source_key)
                observed_at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                received_at = datetime.fromisoformat(
                    row["firestore_create_time"].replace("Z", "+00:00")
                )
                submission, created = Submission.objects.get_or_create(
                    source_record_key=source_key,
                    defaults={
                        "id": submission_id,
                        "request_fingerprint": fingerprint,
                        "kind": Submission.Kind.OBSERVATIONS,
                        "venue": venue,
                        "observed_at_client": observed_at,
                        "received_at_server": received_at,
                        "time_quality": Submission.TimeQuality.UNASSESSED,
                        "vantage_point": Submission.VantagePoint.UNKNOWN,
                        "entry_point": "historical_import",
                        "source_kind": "dataset_import",
                    },
                )
                if created:
                    CoverObservation.objects.create(
                        submission=submission,
                        independence_group_key=submission_id,
                        reported_price_cents=row["reported_price_cents"],
                        interaction_kind=CoverObservation.InteractionKind.DIRECT,
                        displayed_source="historical_import",
                        source_dataset=release.name,
                        admission_snapshot={
                            "admission": "legacy_unit_weight",
                            "resolverVersion": "cover_legacy_import_v1",
                        },
                    )
                    run.rows_accepted += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{release.name}: {run.rows_seen} rows checked, "
                f"{run.rows_accepted} observations created"
            )
        )
