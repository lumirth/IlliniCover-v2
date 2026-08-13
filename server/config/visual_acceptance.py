"""Fault controls that exist only in the loopback visual-acceptance server."""

import time

from django.conf import settings
from django.http import JsonResponse


class VisualAcceptanceFaultMiddleware:
    def __init__(self, get_response):
        if not getattr(settings, "VISUAL_ACCEPTANCE", False):
            raise RuntimeError("visual acceptance middleware requires visual settings")
        self.get_response = get_response

    def __call__(self, request):
        if (
            getattr(settings, "VISUAL_ACCEPTANCE_NOW", None) is not None
            and request.method not in {"GET", "HEAD", "OPTIONS"}
        ):
            return JsonResponse(
                {
                    "code": "visual_acceptance_fixed_clock_read_only",
                    "message": "Unset VISUAL_ACCEPTANCE_NOW before exercising writes.",
                    "requestId": getattr(request, "request_id", "visual-acceptance"),
                },
                status=409,
            )
        fault = getattr(settings, "VISUAL_ACCEPTANCE_FAULT", None)
        if fault is None or not (
            request.method == fault["method"]
            and request.path.startswith(fault["path_prefix"])
        ):
            return self.get_response(request)

        delay_ms = fault["delay_ms"]
        if delay_ms:
            time.sleep(delay_ms / 1_000)
        if fault["status"] is None:
            return self.get_response(request)
        return JsonResponse(
            {
                "code": "visual_acceptance_fault",
                "message": "Local visual-acceptance fault injection.",
                "requestId": getattr(request, "request_id", "visual-acceptance"),
            },
            status=fault["status"],
        )
