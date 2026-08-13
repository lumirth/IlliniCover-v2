import hashlib
import hmac
import ipaddress

from django.conf import settings


def client_address(request) -> str | None:
    """Return Cloud Run's platform-appended client address without trusting the chain.

    Google external load balancers preserve any attacker-supplied prefix, then
    append the observed client and load-balancer addresses. Select from the
    configured trusted suffix, never from the first value. Local/tests fall
    back to REMOTE_ADDR.
    """

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidate = ""
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",")]
        trusted_hops = settings.TRUSTED_XFF_PROXY_HOPS
        if len(parts) > trusted_hops:
            candidate = parts[-(trusted_hops + 1)]
    if not candidate:
        candidate = request.META.get("REMOTE_ADDR", "").strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def keyed_client_identity(request) -> str:
    """Return a non-reversible per-deployment key for allauth rate limiting."""

    address = client_address(request) or "unavailable"
    pepper = settings.NETWORK_METADATA_PEPPER
    digest = hmac.new(pepper.encode(), address.encode(), hashlib.sha256).hexdigest()
    return f"ic_network_{digest}"
