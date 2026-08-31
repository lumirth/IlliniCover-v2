from django.conf import settings
from identity.rate_limits import consume, network_key


class SubmissionRateLimited(Exception):
    pass


def enforce_submission_limits(actor, *, account_id, venue_id, remote_address, now_seconds):
    dimensions = {
        "actor": actor.pk,
        "account": account_id,
        "venue": venue_id,
        "network": network_key(remote_address),
    }
    for dimension, value in dimensions.items():
        if value is not None:
            limit, window = settings.SUBMISSION_RATE_LIMITS[dimension]
            if not consume(f"report:{dimension}:{value}", limit, window, now_seconds):
                raise SubmissionRateLimited


def consume_rate_limit(namespace, identifier, *, limit, window_seconds, now_seconds):
    return consume(f"{namespace}:{identifier}", limit, window_seconds, now_seconds)
