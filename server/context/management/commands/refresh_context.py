from django.core.management.base import BaseCommand
from operations.jobs import JobAlreadyRunning, managed_job

from context.services import refresh_source


class DeferredSourceAdapter:
    def refresh(self):
        return {"changed": False, "reason": "source adapters not configured"}


class Command(BaseCommand):
    help = "Refresh configured context sources; individual source failures degrade independently."

    def handle(self, *args, **options):
        try:
            with managed_job("refresh_context") as run:
                results = [refresh_source("foundation", DeferredSourceAdapter())]
                run.result_summary = {"sources": results}
        except JobAlreadyRunning:
            self.stdout.write("refresh_context is already running")
            return
        self.stdout.write(self.style.SUCCESS("context refresh completed"))
