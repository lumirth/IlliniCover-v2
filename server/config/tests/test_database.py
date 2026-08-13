import pytest
from django.core.exceptions import ImproperlyConfigured

from config.database import database_from_url


def test_database_url_keeps_only_supported_transport_options():
    configured = database_from_url(
        "postgresql://runtime:p%40ss@db.example.test:5433/app"
        "?sslmode=verify-full&sslrootcert=system&channel_binding=require&application_name=ignored"
    )

    assert configured == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "app",
        "USER": "runtime",
        "PASSWORD": "p@ss",
        "HOST": "db.example.test",
        "PORT": 5433,
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": {
            "sslmode": "verify-full",
            "sslrootcert": "system",
            "channel_binding": "require",
        },
    }


def test_database_url_rejects_non_postgresql_values():
    with pytest.raises(ImproperlyConfigured, match="must be a PostgreSQL URL"):
        database_from_url("sqlite:///tmp/not-production.sqlite3")
