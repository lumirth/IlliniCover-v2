def redact_sentry_event(event, _hint):
    """Allow only failure shape; never send request, user, message, locals, or breadcrumbs."""

    safe = {
        key: event[key]
        for key in ("event_id", "timestamp", "level", "release", "environment")
        if key in event
    }
    values = event.get("exception", {}).get("values", [])
    safe["exception"] = {
        "values": [
            {key: value[key] for key in ("type", "module") if key in value} for value in values
        ]
    }
    return safe


def configure_sentry(*, dsn, environment, release):
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        send_client_reports=False,
        traces_sample_rate=0,
        before_send=redact_sentry_event,
    )
