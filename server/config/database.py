from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def database_from_url(value: str) -> dict[str, object]:
    """Translate the small PostgreSQL URL surface accepted by every environment."""

    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path:
        raise ImproperlyConfigured("DATABASE_URL must be a PostgreSQL URL")
    options = dict(parse_qsl(parsed.query))
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.removeprefix("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": {
            key: option
            for key, option in options.items()
            if key in {"sslmode", "sslrootcert", "channel_binding"}
        },
    }
