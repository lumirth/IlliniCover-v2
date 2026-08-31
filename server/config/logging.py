import json
import logging
import re
from datetime import UTC, datetime

from django.conf import settings

PARAMETER = re.compile(r"<[^>]+>")


def generalized_request_route(request):
    route = getattr(getattr(request, "resolver_match", None), "route", "")
    return "/" + PARAMETER.sub(":param", route).lstrip("/") if route else "/unmatched"


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": "exception" if record.exc_info else str(record.msg)[:80],
            "environment": settings.DEPLOYMENT_ENVIRONMENT,
            "revision": settings.CODE_REVISION,
        }
        for key in ("request_id", "endpoint", "status_code", "duration_ms"):
            value = getattr(record, key, None)
            if isinstance(value, str | int | float):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"))
