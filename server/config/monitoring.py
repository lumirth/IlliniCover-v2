from __future__ import annotations

import re
from typing import Any, cast

from sentry_sdk.types import Event

_SAFE_EVENT_FIELDS = (
    "event_id",
    "timestamp",
    "platform",
    "level",
    "release",
    "environment",
)
_SAFE_FRAME_FIELDS = ("filename", "function", "module", "lineno", "colno")
_SAFE_TAG_FIELDS = {
    "code_revision",
    "decision_id",
    "error_code",
    "job_id",
    "model_release",
    "request_id",
}
_REQUEST_ID = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _safe_stacktrace(value: object) -> dict[str, list[dict[str, object]]] | None:
    if not isinstance(value, dict) or not isinstance(value.get("frames"), list):
        return None
    frames: list[dict[str, object]] = []
    for candidate in value["frames"]:
        if not isinstance(candidate, dict):
            continue
        frame = {
            field: candidate[field]
            for field in _SAFE_FRAME_FIELDS
            if field in candidate and isinstance(candidate[field], str | int | float | bool)
        }
        if frame:
            frames.append(frame)
    return {"frames": frames} if frames else None


def redact_sentry_event(event: Event, _hint: dict[str, Any]) -> Event | None:
    """Return a fail-closed operational error receipt for Sentry.

    Request bodies, headers, cookies, query strings, user objects, breadcrumbs,
    exception messages, and frame locals are deliberately not copied. This is
    stricter than Sentry's key-name scrubber because IlliniCover bodies can
    contain nested exact location and custom opaque credentials.
    """

    source = cast(dict[str, Any], event)
    safe: dict[str, Any] = {}
    for field in _SAFE_EVENT_FIELDS:
        scalar = source.get(field)
        if isinstance(scalar, str | int | float | bool):
            safe[field] = scalar
    request = event.get("request")
    if isinstance(request, dict):
        safe_request: dict[str, str] = {}
        method = request.get("method")
        if isinstance(method, str):
            safe_request["method"] = method.upper()[:16]
        headers = request.get("headers")
        if isinstance(headers, dict):
            request_id = next(
                (
                    value
                    for key, value in headers.items()
                    if isinstance(key, str)
                    and key.lower() == "x-request-id"
                    and isinstance(value, str)
                    and _REQUEST_ID.fullmatch(value)
                ),
                None,
            )
            if request_id:
                safe_request["x-request-id"] = request_id
        if safe_request:
            safe["request"] = safe_request

    tags = event.get("tags")
    if isinstance(tags, dict):
        safe_tags = {
            key: value
            for key, value in tags.items()
            if key in _SAFE_TAG_FIELDS
            and isinstance(value, str | int | float | bool)
        }
        if safe_tags:
            safe["tags"] = safe_tags

    exception = event.get("exception")
    if isinstance(exception, dict) and isinstance(exception.get("values"), list):
        values: list[dict[str, object]] = []
        for candidate in exception["values"]:
            if not isinstance(candidate, dict):
                continue
            value: dict[str, object] = {}
            for field in ("type", "module"):
                if isinstance(candidate.get(field), str):
                    value[field] = candidate[field][:200]
            stacktrace = _safe_stacktrace(candidate.get("stacktrace"))
            if stacktrace:
                value["stacktrace"] = stacktrace
            if value:
                values.append(value)
        if values:
            safe["exception"] = {"values": values}

    return cast(Event, safe)


def configure_sentry(*, dsn: str, environment: str, release: str) -> None:
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        enable_http_request_source=False,
        send_client_reports=False,
        traces_sample_rate=0.0,
        before_send=redact_sentry_event,
    )
