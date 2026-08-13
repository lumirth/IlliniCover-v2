from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from operations.management.commands.nightly import NIGHTLY_COMMANDS
from operations.models import JobRun


@pytest.mark.django_db
def test_nightly_runs_every_independent_step_before_reporting_aggregate_failure():
    called = []

    def run_step(name, **_options):
        called.append(name)
        if name in {"refresh_context", "reconcile_revenuecat"}:
            raise CommandError("provider-specific detail must not enter the aggregate receipt")

    with patch("operations.management.commands.nightly.call_command", side_effect=run_step):
        with pytest.raises(CommandError, match="refresh_context, reconcile_revenuecat"):
            call_command("nightly", verbosity=0)

    assert called == list(NIGHTLY_COMMANDS)
    receipt = JobRun.objects.get(name="nightly")
    assert receipt.status == "failed"
    assert receipt.error == "CommandError: job execution failed; inspect redacted error monitoring"
    assert receipt.result_summary == {"steps": [
        {"command": name, "status": (
            "failed" if name in {"refresh_context", "reconcile_revenuecat"} else "succeeded"
        )}
        for name in NIGHTLY_COMMANDS
    ], "failureCount": 2}
