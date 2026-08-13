import logging
import time
import uuid

from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers

from config.logging import generalized_request_route

logger = logging.getLogger("illinicover.request")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = _request_id(supplied)
        request.request_id = request_id  # type: ignore[attr-defined]
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        decision_id = getattr(request, "decision_id", None)
        logger.info(
            "request.completed",
            extra={
                "request_id": request_id,
                "decision_id": str(decision_id) if decision_id is not None else None,
                "endpoint": generalized_request_route(request),
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response


class SensitiveResponseCacheMiddleware:
    """Prevent credential-dependent product responses from being reused."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        path = request.path.rstrip("/")
        no_store = (
            bool(
                request.headers.get("X-Session-Token")
                or request.headers.get("X-Installation-Token")
                or request.headers.get("Authorization")
            )
            or path == "/api/v2/me"
            or path.startswith("/api/v2/me/")
            or path.startswith("/api/v2/installations")
            or path.startswith("/api/v2/account-deletions/")
            or (path.startswith("/api/v2/venues/") and path.endswith("/cover/time-machine"))
        )
        is_history = path.startswith("/api/v2/venues/") and path.endswith("/cover/history")
        if is_history:
            patch_vary_headers(response, ["X-Session-Token"])
            no_store = no_store or bool(request.headers.get("X-Session-Token"))
        if no_store:
            response["Cache-Control"] = "no-store"
        return response


def _request_id(value: str) -> str:
    """Accept only canonical random UUIDs; replace all other client input.

    Request IDs cross the production logging boundary. Treating arbitrary
    client text as an identifier would let a caller persist encoded or stable
    user data in operational logs.
    """

    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        return str(uuid.uuid4())
    if parsed.version != 4 or str(parsed) != value.lower():
        return str(uuid.uuid4())
    return str(parsed)
