import logging
import time
import uuid

from config.logging import generalized_request_route

logger = logging.getLogger("illinicover.request")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            supplied = uuid.UUID(request.headers.get("X-Request-ID", ""), version=4)
        except ValueError:
            supplied = uuid.uuid4()
        request.request_id = str(supplied)
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        logger.info(
            "request.completed",
            extra={
                "request_id": request.request_id,
                "endpoint": generalized_request_route(request),
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response


class SensitiveResponseCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(("/api/me", "/api/installations")) or any(
            request.headers.get(name)
            for name in ("X-Session-Token", "X-Installation-Token", "Authorization")
        ):
            response["Cache-Control"] = "no-store"
        return response
