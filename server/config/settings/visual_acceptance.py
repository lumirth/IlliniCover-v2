"""Fail-closed local settings for simulator visual acceptance.

This module deliberately requires an explicit opt-in and a repository-scoped
SQLite path. It must never be used for a deployed service or a shared database.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.dateparse import parse_datetime

from .development import *  # noqa: F403

if os.environ.get("VISUAL_ACCEPTANCE_ENABLED") != "1":
    raise ImproperlyConfigured("VISUAL_ACCEPTANCE_ENABLED=1 is required")
if any(
    os.environ.get(name)
    for name in ("K_SERVICE", "K_REVISION", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION")
):
    raise ImproperlyConfigured("Visual acceptance settings refuse Cloud Run")
if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_DIRECT"):
    raise ImproperlyConfigured("Visual acceptance refuses external database URLs")

_root = (REPOSITORY_DIR / ".local" / "visual-acceptance").resolve()  # noqa: F405
_raw_database = os.environ.get("VISUAL_ACCEPTANCE_DB", str(_root / "visual.sqlite3"))
_database = Path(_raw_database).resolve()
if _database.parent != _root or _database.suffix != ".sqlite3":
    raise ImproperlyConfigured(
        f"VISUAL_ACCEPTANCE_DB must be a direct .sqlite3 child of {_root}"
    )

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": _database}}
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
DEBUG = True
VISUAL_ACCEPTANCE = True
if not CODE_REVISION.startswith("src-") or len(CODE_REVISION) != 68:  # noqa: F405
    raise ImproperlyConfigured(
        "Visual acceptance requires an exact src-<sha256> CODE_REVISION"
    )

_raw_now = os.environ.get("VISUAL_ACCEPTANCE_NOW", "").strip()
VISUAL_ACCEPTANCE_NOW = None
if _raw_now:
    VISUAL_ACCEPTANCE_NOW = parse_datetime(_raw_now)
    if VISUAL_ACCEPTANCE_NOW is None or VISUAL_ACCEPTANCE_NOW.tzinfo is None:
        raise ImproperlyConfigured("VISUAL_ACCEPTANCE_NOW must be an aware ISO 8601 timestamp")

VISUAL_ACCEPTANCE_FAULT = None
_raw_fault = os.environ.get("VISUAL_ACCEPTANCE_FAULT", "").strip()
if _raw_fault:
    parts = _raw_fault.split(":")
    if len(parts) not in (3, 4):
        raise ImproperlyConfigured(
            "VISUAL_ACCEPTANCE_FAULT must be METHOD:/api/v2/path:STATUS_OR_PASS[:DELAY_MS]"
        )
    method, path_prefix, raw_status, *raw_delay = parts
    method = method.upper()
    if method not in {"GET", "POST"} or not path_prefix.startswith("/api/v2/"):
        raise ImproperlyConfigured("Visual acceptance faults require GET/POST and /api/v2/")
    status = None if raw_status == "pass" else int(raw_status)
    delay_ms = int(raw_delay[0]) if raw_delay else 0
    if (status is not None and not 400 <= status <= 599) or not 0 <= delay_ms <= 5_000:
        raise ImproperlyConfigured("Visual acceptance fault status or delay is out of range")
    VISUAL_ACCEPTANCE_FAULT = {
        "method": method,
        "path_prefix": path_prefix,
        "status": status,
        "delay_ms": delay_ms,
    }

MIDDLEWARE = [*MIDDLEWARE]  # noqa: F405
_request_id_index = MIDDLEWARE.index("config.middleware.RequestIdMiddleware")
MIDDLEWARE.insert(
    _request_id_index + 1,
    "config.visual_acceptance.VisualAcceptanceFaultMiddleware",
)
