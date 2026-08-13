from unittest.mock import patch

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
def test_liveness_and_readiness_are_independently_available():
    client = Client()

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert live.headers["X-Request-ID"]
    assert ready.headers["X-Request-ID"]


@pytest.mark.django_db
def test_deep_readiness_refuses_a_pending_migration_plan():
    with patch("config.health.MigrationExecutor") as executor:
        executor.return_value.loader.graph.leaf_nodes.return_value = [("covers", "9999")]
        executor.return_value.migration_plan.return_value = [object()]
        response = Client().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@override_settings(
    DEPLOYMENT_ENVIRONMENT="production",
    EMAIL_HOST="",
    EMAIL_HOST_USER="",
    EMAIL_HOST_PASSWORD="",
    REVENUECAT_WEBHOOK_AUTHORIZATION="",
    REVENUECAT_WEBHOOK_SIGNING_SECRET="",
    REVENUECAT_SECRET_API_KEY="",
)
def test_production_readiness_refuses_missing_email_and_billing_integrations():
    response = Client().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_public_privacy_policy_is_readable_and_security_scoped():
    response = Client().get("/privacy")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["Cache-Control"] == "public, max-age=3600"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert b"IlliniCover privacy policy" in response.content
    assert b"Google Cloud Run automatically emits" in response.content
