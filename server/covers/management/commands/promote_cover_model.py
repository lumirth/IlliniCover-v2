from django.core.management.base import BaseCommand, CommandError
from operations.jobs import JobAlreadyRunning, managed_job
from operations.models import AuditEvent

from covers.modeling import HistoricalModel
from covers.models import (
    CoverModelEvaluationReceipt,
    CoverModelRelease,
    CoverTrainingRevision,
)
from covers.releases import ChallengerEvaluationError, promote_release


class Command(BaseCommand):
    help = "Explicitly promote an eligible historical cover release."

    def add_arguments(self, parser):
        parser.add_argument("release_id")
        parser.add_argument("--evaluation-receipt")

    def handle(self, *args, **options):
        try:
            release = CoverModelRelease.objects.get(pk=options["release_id"])
        except (CoverModelRelease.DoesNotExist, ValueError) as error:
            raise CommandError("Unknown cover model release") from error
        if release.model_kind not in {"historical", "historical_challenger"}:
            raise CommandError("Only historical cover releases can become authoritative")
        try:
            HistoricalModel.from_artifact(release.parameters_or_artifact)
        except (KeyError, TypeError, ValueError) as error:
            raise CommandError(
                "Release does not contain a valid historical model artifact"
            ) from error
        if not CoverTrainingRevision.objects.filter(
            data_revision=release.training_data_revision
        ).exists():
            raise CommandError("Release training revision is unavailable")
        evaluation_receipt = None
        if options["evaluation_receipt"]:
            try:
                evaluation_receipt = CoverModelEvaluationReceipt.objects.get(
                    pk=options["evaluation_receipt"]
                )
            except (CoverModelEvaluationReceipt.DoesNotExist, ValueError) as error:
                raise CommandError("Unknown cover model evaluation receipt") from error

        try:
            with managed_job("promote_cover_model") as run:
                previous = CoverModelRelease.objects.filter(is_authoritative=True).first()
                try:
                    promoted = promote_release(
                        release,
                        evaluation_receipt=evaluation_receipt,
                    )
                except ChallengerEvaluationError as error:
                    raise CommandError(str(error)) from error
                AuditEvent.objects.create(
                    kind="cover_model_promoted",
                    actor_kind="management_command",
                    target_reference=str(promoted.pk),
                    metadata={
                        "previousReleaseId": str(previous.pk) if previous else None,
                        "modelVersion": promoted.model_version,
                        "trainingDataRevision": promoted.training_data_revision,
                        "evaluationReceiptId": (
                            str(evaluation_receipt.pk) if evaluation_receipt else None
                        ),
                        "evaluationReceiptSha256": (
                            evaluation_receipt.receipt_sha256 if evaluation_receipt else None
                        ),
                    },
                )
                run.result_summary = {
                    "promotedReleaseId": str(promoted.pk),
                    "previousReleaseId": str(previous.pk) if previous else None,
                    "evaluationReceiptId": (
                        str(evaluation_receipt.pk) if evaluation_receipt else None
                    ),
                }
        except JobAlreadyRunning:
            self.stdout.write("cover model promotion is already running")
            return
        self.stdout.write(self.style.SUCCESS(f"promoted cover model {release.pk}"))
