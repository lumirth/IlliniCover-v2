from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from operations.jobs import JobAlreadyRunning, managed_job

NIGHTLY_COMMANDS = (
    "refresh_context",
    "refresh_cover_models",
    "refresh_deal_predictions",
    "reconcile_revenuecat",
    "cleanup",
)


class Command(BaseCommand):
    help = "Run the bounded nightly maintenance sequence in one scale-to-zero job container."

    def handle(self, *args, **options):
        failed: list[str] = []
        try:
            with managed_job("nightly") as run:
                steps = []
                for command in NIGHTLY_COMMANDS:
                    try:
                        call_command(command, verbosity=options["verbosity"])
                    except Exception:
                        failed.append(command)
                        steps.append({"command": command, "status": "failed"})
                    else:
                        steps.append({"command": command, "status": "succeeded"})
                run.result_summary = {"steps": steps, "failureCount": len(failed)}
                if failed:
                    raise CommandError(
                        "nightly maintenance failed after all steps ran: " + ", ".join(failed)
                    )
        except JobAlreadyRunning:
            raise CommandError("nightly maintenance is already running") from None
        self.stdout.write(self.style.SUCCESS("nightly maintenance completed"))
