from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from operations.models import JobRun


class JobAlreadyRunning(Exception):
    pass


@contextmanager
def managed_job(name: str):
    run = _begin_run(name)
    try:
        yield run
    except Exception as error:
        run.status = "failed"
        run.error = _safe_error(error)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error", "result_summary", "completed_at"])
        raise
    else:
        run.status = "succeeded"
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result_summary", "completed_at"])


def _begin_run(name: str) -> JobRun:
    """Create one durable running receipt without requiring a direct DB session.

    The short transaction-scoped advisory lock is safe through a transaction-
    pooled PostgreSQL endpoint. The durable running receipt guards the rest of
    the job after that transaction ends. A crashed execution is recoverable
    after a timeout longer than the configured Cloud Run task timeout.
    """

    now = timezone.now()
    stale_after = timedelta(seconds=getattr(settings, "JOB_RUN_STALE_AFTER_SECONDS", 7_200))
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                    [f"illinicover-job:{name}"],
                )
                if not bool(cursor.fetchone()[0]):
                    raise JobAlreadyRunning(name)

        running = list(
            JobRun.objects.select_for_update()
            .filter(name=name, status="running")
            .order_by("started_at")
        )
        if any(run.started_at >= now - stale_after for run in running):
            raise JobAlreadyRunning(name)
        for stale in running:
            stale.status = "failed"
            stale.error = "StaleJobRun: execution lease expired before completion"
            stale.completed_at = now
            stale.save(update_fields=["status", "error", "completed_at"])

        return JobRun.objects.create(name=name, code_revision=settings.CODE_REVISION)


def _safe_error(error: Exception) -> str:
    """Persist only the exception class and a bounded generic description."""
    safe_messages = {
        JobAlreadyRunning: "another execution already holds the job lock",
    }
    for error_type, message in safe_messages.items():
        if isinstance(error, error_type):
            return f"{error_type.__name__}: {message}"
    return f"{type(error).__name__}: job execution failed; inspect redacted error monitoring"
