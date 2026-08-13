from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from operations.jobs import JobAlreadyRunning, managed_job
from operations.models import AuditEvent

from covers.models import CoverModelRelease
from covers.releases import ChallengerEvaluationError, evaluate_challenger


class Command(BaseCommand):
    help = "Compare one cover challenger with its baseline on a chronological holdout."

    def add_arguments(self, parser):
        parser.add_argument("release_id")
        parser.add_argument("--cutoff")

    def handle(self, *args, **options):
        try:
            release = CoverModelRelease.objects.get(pk=options["release_id"])
        except (CoverModelRelease.DoesNotExist, ValueError) as error:
            raise CommandError("Unknown cover model release") from error
        cutoff = timezone.now()
        if options["cutoff"]:
            parsed_cutoff = parse_datetime(options["cutoff"])
            if parsed_cutoff is None or timezone.is_naive(parsed_cutoff):
                raise CommandError("--cutoff must be an RFC3339 timestamp with a time zone")
            cutoff = parsed_cutoff

        try:
            with managed_job("evaluate_cover_challenger") as run:
                try:
                    receipt, created = evaluate_challenger(
                        release,
                        evaluation_cutoff=cutoff,
                    )
                except ChallengerEvaluationError as error:
                    raise CommandError(str(error)) from error
                AuditEvent.objects.create(
                    kind="cover_model_evaluated",
                    actor_kind="management_command",
                    target_reference=str(release.pk),
                    metadata={
                        "evaluationReceiptId": str(receipt.pk),
                        "receiptSha256": receipt.receipt_sha256,
                        "challengerWon": receipt.challenger_won,
                        "promotionEligible": receipt.promotion_eligible,
                        "created": created,
                    },
                )
                run.result_summary = {
                    "evaluationReceiptId": str(receipt.pk),
                    "receiptSha256": receipt.receipt_sha256,
                    "challengerWon": receipt.challenger_won,
                    "promotionEligible": receipt.promotion_eligible,
                    "created": created,
                }
        except JobAlreadyRunning:
            self.stdout.write("cover challenger evaluation is already running")
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"evaluated cover challenger {release.pk}: {receipt.receipt_sha256}"
            )
        )
