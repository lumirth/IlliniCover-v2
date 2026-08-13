import json
import uuid
from unittest.mock import Mock

from config.monitoring import configure_sentry, redact_sentry_event


def test_sentry_event_is_a_fail_closed_operational_receipt():
    request_id = str(uuid.uuid4())
    event = {
        "event_id": "event-1",
        "release": "src-abc",
        "environment": "production",
        "transaction": "/api/v2/account-deletions/123e4567-e89b-42d3-a456-426614174000",
        "user": {"email": "private@example.com"},
        "request": {
            "method": "post",
            "url": (
                "https://api.example.test/api/v2/account-deletions/"
                "123e4567-e89b-42d3-a456-426614174000?email=private%40example.com"
            ),
            "headers": {
                "X-Request-ID": request_id,
                "X-Installation-Token": "ic_install_top_secret",
                "X-Session-Token": "top_secret_session",
                "Cookie": "session=top_secret_cookie",
            },
            "data": {
                "location": {"latitude": 40.109, "longitude": -88.227},
                "installationToken": "ic_install_nested_secret",
            },
        },
        "breadcrumbs": {"values": [{"message": "private@example.com"}]},
        "extra": {"payload": {"latitude": 40.109}},
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "module": "identity.api",
                    "value": "failed for ic_install_top_secret at 40.109",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "server/identity/api.py",
                                "function": "create_installation",
                                "lineno": 42,
                                "vars": {"token": "ic_install_top_secret"},
                                "context_line": "raise RuntimeError(raw_token)",
                            }
                        ]
                    },
                }
            ]
        },
    }

    redacted = redact_sentry_event(event, {})
    serialized = json.dumps(redacted, sort_keys=True)

    assert redacted["request"] == {
        "method": "POST",
        "x-request-id": request_id,
    }
    assert "transaction" not in redacted
    assert redacted["exception"]["values"][0] == {
        "type": "RuntimeError",
        "module": "identity.api",
        "stacktrace": {
            "frames": [
                {
                    "filename": "server/identity/api.py",
                    "function": "create_installation",
                    "lineno": 42,
                }
            ]
        },
    }
    for secret in (
        "private@example.com",
        "ic_install_top_secret",
        "top_secret_session",
        "top_secret_cookie",
        "40.109",
        "-88.227",
    ):
        assert secret not in serialized


def test_sentry_configuration_disables_sensitive_capture(monkeypatch):
    init = Mock()
    monkeypatch.setattr("sentry_sdk.init", init)

    configure_sentry(
        dsn="https://public@example.invalid/1",
        environment="production",
        release="src-test",
    )

    assert init.call_args.kwargs == {
        "dsn": "https://public@example.invalid/1",
        "environment": "production",
        "release": "src-test",
        "send_default_pii": False,
        "max_request_body_size": "never",
        "include_local_variables": False,
        "enable_http_request_source": False,
        "send_client_reports": False,
        "traces_sample_rate": 0.0,
        "before_send": redact_sentry_event,
    }
