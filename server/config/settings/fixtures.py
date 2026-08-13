"""Isolated settings for exporting checked-in canonical API fixtures."""

import os
from datetime import datetime

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if any(
    os.environ.get(name)
    for name in (
        "DATABASE_URL",
        "DATABASE_URL_DIRECT",
        "K_SERVICE",
        "K_REVISION",
        "CLOUD_RUN_JOB",
        "CLOUD_RUN_EXECUTION",
    )
):
    raise ImproperlyConfigured("Canonical fixture export refuses deployed or external state")

_fixture_root = (REPOSITORY_DIR / ".local" / "visual-acceptance").resolve()  # noqa: F405
_fixture_database = (_fixture_root / "canonical-fixtures.sqlite3").resolve()
if _fixture_database.parent != _fixture_root:
    raise ImproperlyConfigured("Canonical fixture database escaped its repository boundary")

DEBUG = True
ALLOWED_HOSTS = ["testserver"]
SESSION_COOKIE_SECURE = False
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _fixture_database,
    }
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CANONICAL_FIXTURE_EXPORT = True
VISUAL_ACCEPTANCE = True
VISUAL_ACCEPTANCE_NOW = datetime.fromisoformat("2026-08-12T21:15:00-05:00")
CODE_REVISION = "fixture-canonical-v1"
