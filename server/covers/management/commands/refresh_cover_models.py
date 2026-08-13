from django.core.management.base import BaseCommand
from operations.jobs import JobAlreadyRunning, managed_job

from covers.releases import (
    capture_completed_training_rows,
    evaluate_non_authoritative_releases,
    train_completed_night_challenger,
)


class Command(BaseCommand):
    help = "Snapshot completed-night training evidence and evaluate registered challengers."

    def handle(self, *args, **options):
        try:
            with managed_job("refresh_cover_models") as run:
                frozen_selection = capture_completed_training_rows()
                revision = frozen_selection.revision
                challenger = train_completed_night_challenger(
                    frozen_selection=frozen_selection
                )
                shadow_count = evaluate_non_authoritative_releases(
                    knowledge_cutoff=revision.knowledge_cutoff
                )
                run.result_summary = {
                    "trainingRevision": str(revision.id),
                    "dataRevision": revision.data_revision,
                    "challengerRelease": str(challenger.id) if challenger else None,
                    "shadowPredictionsCreated": shadow_count,
                    "promotion": "explicit_only",
                }
        except JobAlreadyRunning:
            self.stdout.write("refresh_cover_models is already running")
            return
        self.stdout.write(self.style.SUCCESS("cover training snapshot and shadow pass completed"))
