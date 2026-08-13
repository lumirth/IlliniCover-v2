import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_json_secret_bundle_supplies_values_and_environment_overrides(monkeypatch):
    monkeypatch.setenv(
        "ILLINICOVER_SECRETS_JSON",
        '{"DATABASE_URL":"bundle-database","SESSION_TOKEN_HMAC_KEY":"bundle-session"}',
    )
    monkeypatch.setenv("DATABASE_URL", "environment-database")
    import config.secrets

    module = importlib.reload(config.secrets)

    assert module.secret_value("DATABASE_URL") == "environment-database"
    assert module.secret_value("SESSION_TOKEN_PEPPER", bundle_name="SESSION_TOKEN_HMAC_KEY") == (
        "bundle-session"
    )


def test_invalid_secret_bundle_fails_closed_without_echoing_value(monkeypatch):
    monkeypatch.setenv("ILLINICOVER_SECRETS_JSON", "secret-not-json")
    import config.secrets

    with pytest.raises(ImproperlyConfigured, match="must be valid JSON") as caught:
        importlib.reload(config.secrets)

    assert "secret-not-json" not in str(caught.value)
