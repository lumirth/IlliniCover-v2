from django.core.management.base import BaseCommand, CommandError
from operations.jobs import JobAlreadyRunning, managed_job
from operations.models import AuditEvent

from covers.models import CoverModelRelease
from covers.releases import ChallengerEvaluationError, issue_recovery_release


class Command(BaseCommand):
    help = "Issue a fresh candidate identity that reproduces one retired cover release."

    def add_arguments(self, parser):
        parser.add_argument("source_release_id")
        parser.add_argument("--model-version", required=True)

    def handle(self, *args, **options):
        try:
            source = CoverModelRelease.objects.get(pk=options["source_release_id"])
        except (CoverModelRelease.DoesNotExist, ValueError) as error:
            raise CommandError("Unknown recovery source release") from error

        try:
            with managed_job("issue_cover_model_recovery") as run:
                try:
                    candidate, created = issue_recovery_release(
                        source,
                        model_version=options["model_version"],
                    )
                except ChallengerEvaluationError as error:
                    raise CommandError(str(error)) from error
                AuditEvent.objects.create(
                    kind="cover_model_recovery_issued",
                    actor_kind="management_command",
                    target_reference=str(candidate.pk),
                    metadata={
                        "sourceReleaseId": str(source.pk),
                        "modelVersion": candidate.model_version,
                        "baselineReleaseId": candidate.evaluation_metrics["baselineReleaseId"],
                        "created": created,
                    },
                )
                run.result_summary = {
                    "sourceReleaseId": str(source.pk),
                    "candidateReleaseId": str(candidate.pk),
                    "modelVersion": candidate.model_version,
                    "created": created,
                    "promotion": "explicit_only",
                }
        except JobAlreadyRunning:
            self.stdout.write("cover model recovery issuance is already running")
            return
        self.stdout.write(
            self.style.SUCCESS(f"issued cover recovery candidate {candidate.pk} from {source.pk}")
        )
