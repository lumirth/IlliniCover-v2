import pytest

from context.models import SourceHealth
from context.services import refresh_source


class FailingAdapter:
    def refresh(self):
        raise TimeoutError("provider URL and credential must not be persisted")


@pytest.mark.django_db
def test_context_failure_records_degraded_health_without_raising_or_storing_detail():
    result = refresh_source("weather", FailingAdapter())

    assert result == {"source": "weather", "status": "degraded", "error": "TimeoutError"}
    health = SourceHealth.objects.get(source_identifier="weather")
    assert health.last_failure_at is not None
    assert health.last_error == "TimeoutError"
    assert "provider URL" not in health.last_error
