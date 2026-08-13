import json
import logging
import re
import traceback
from datetime import UTC, datetime

from django.conf import settings
from django.http import HttpRequest

_SAFE_EVENT_NAMES = {
    "context.refresh_failed",
    "cover.decision_served",
    "request.completed",
}
_SAFE_LOGGER_PREFIXES = ("allauth", "django", "gunicorn", "illinicover", "sentry_sdk")
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_UUID_IDENTIFIER = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ROUTE_PARAMETER = re.compile(r"<[^>]+>")


class GeneralizedRoute(str):
    """A route template derived from Django's resolver, never a caller path."""


def generalized_request_route(request: HttpRequest) -> GeneralizedRoute:
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", None)
    if not isinstance(route, str) or not route:
        return GeneralizedRoute("/unmatched")
    generalized = "/" + _ROUTE_PARAMETER.sub(":param", route).lstrip("/")
    return GeneralizedRoute(generalized[:500])


def _event_name(record: logging.LogRecord) -> str:
    if isinstance(record.msg, str) and not record.args and record.msg in _SAFE_EVENT_NAMES:
        return record.msg
    return "exception.captured" if record.exc_info else "log.event"


def _logger_name(value: str) -> str:
    return value if value.startswith(_SAFE_LOGGER_PREFIXES) else "application"


def _route_only(value: object) -> str | None:
    return str(value) if isinstance(value, GeneralizedRoute) else None


def _exception_receipt(record: logging.LogRecord) -> dict[str, object] | None:
    if not record.exc_info or not record.exc_info[0]:
        return None
    exception_type = record.exc_info[0]
    receipt: dict[str, object] = {
        "type": exception_type.__name__,
        "module": exception_type.__module__,
    }
    if record.exc_info[2]:
        receipt["frames"] = [
            {
                "filename": frame.filename,
                "function": frame.name,
                "lineno": frame.lineno,
            }
            for frame in traceback.extract_tb(record.exc_info[2])[-50:]
        ]
    return receipt


class JsonFormatter(logging.Formatter):
    """Format an allowlisted operational receipt without copying arbitrary text.

    Log messages and exception messages can contain credentials, email addresses,
    or nested report data. Only static event names and selected scalar metadata
    cross the production logging boundary.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": _logger_name(record.name),
            "message": _event_name(record),
            "code_revision": str(getattr(settings, "CODE_REVISION", "development")),
            "environment": str(getattr(settings, "DEPLOYMENT_ENVIRONMENT", "local")),
        }
        endpoint = _route_only(getattr(record, "endpoint", None))
        if endpoint:
            payload["endpoint"] = endpoint
        request_id = getattr(record, "request_id", None)
        if isinstance(request_id, str) and _UUID_IDENTIFIER.fullmatch(request_id):
            payload["request_id"] = request_id
        for key in ("job_id", "decision_id"):
            value = getattr(record, key, None)
            if isinstance(value, str) and _UUID_IDENTIFIER.fullmatch(value):
                payload[key] = value
        error_code = getattr(record, "error_code", None)
        if isinstance(error_code, str) and _SAFE_ERROR_CODE.fullmatch(error_code):
            payload["error_code"] = error_code
        status_code = getattr(record, "status_code", None)
        if isinstance(status_code, int) and 100 <= status_code <= 599:
            payload["status_code"] = status_code
        duration_ms = getattr(record, "duration_ms", None)
        if isinstance(duration_ms, int | float) and duration_ms >= 0:
            payload["duration_ms"] = duration_ms
        exception = _exception_receipt(record)
        if exception:
            payload["exception"] = exception
        return json.dumps(payload, separators=(",", ":"), default=str)
