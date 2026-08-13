import logging

from django.utils import timezone

from context.models import SourceHealth

logger = logging.getLogger("illinicover.context")


def refresh_source(source_identifier: str, adapter) -> dict:
    """Refresh one typed context source without invalidating its last good rows."""
    health, _ = SourceHealth.objects.get_or_create(source_identifier=source_identifier)
    try:
        result = adapter.refresh()
    except Exception as error:
        health.last_failure_at = timezone.now()
        health.last_error = type(error).__name__
        health.save(update_fields=["last_failure_at", "last_error", "updated_at"])
        logger.warning(
            "context.refresh_failed",
            extra={"error_code": "context_refresh_failed", "endpoint": source_identifier},
        )
        return {"source": source_identifier, "status": "degraded", "error": type(error).__name__}
    health.last_success_at = timezone.now()
    health.last_error = ""
    health.save(update_fields=["last_success_at", "last_error", "updated_at"])
    return {"source": source_identifier, "status": "ok", "result": result}
