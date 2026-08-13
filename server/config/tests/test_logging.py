import json
import logging
import uuid

from config.logging import GeneralizedRoute, JsonFormatter


def _raise_sensitive_error():
    raise RuntimeError(
        "email=user@example.com token=secret latitude=40.1106 longitude=-88.2073"
    )


def test_json_formatter_emits_fail_closed_exception_receipt():
    request_id = str(uuid.uuid4())
    try:
        _raise_sensitive_error()
    except RuntimeError:
        record = logging.getLogger("django.request").makeRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            "Internal Server Error: %s",
            ("token=secret",),
            exc_info=__import__("sys").exc_info(),
            extra={
                "endpoint": GeneralizedRoute("/api/v2/account-deletions/:param"),
                "request_id": request_id,
                "email": "user@example.com",
                "latitude": 40.1106,
            },
        )

    payload = json.loads(JsonFormatter().format(record))
    rendered = json.dumps(payload)

    assert payload["message"] == "exception.captured"
    assert payload["endpoint"] == "/api/v2/account-deletions/:param"
    assert payload["request_id"] == request_id
    assert payload["exception"]["type"] == "RuntimeError"
    assert payload["exception"]["frames"][-1]["function"] == "_raise_sensitive_error"
    for sensitive in (
        "user@example.com",
        "token=secret",
        "40.1106",
        "-88.2073",
        "Internal Server Error",
    ):
        assert sensitive not in rendered


def test_json_formatter_keeps_only_static_event_and_allowlisted_metadata():
    decision_id = str(uuid.uuid4())
    record = logging.getLogger("illinicover.request").makeRecord(
        "illinicover.request",
        logging.INFO,
        __file__,
        1,
        "request.completed",
        (),
        exc_info=None,
        extra={
            "endpoint": GeneralizedRoute("/api/v2/venues"),
            "status_code": 200,
            "duration_ms": 12.5,
            "error_code": "ok",
            "decision_id": decision_id,
        },
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "request.completed"
    assert payload["endpoint"] == "/api/v2/venues"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.5
    assert payload["error_code"] == "ok"
    assert payload["decision_id"] == decision_id
    assert payload["code_revision"] == "development"
    assert payload["environment"] == "local"


def test_json_formatter_drops_non_uuid_request_id():
    record = logging.getLogger("illinicover.request").makeRecord(
        "illinicover.request",
        logging.INFO,
        __file__,
        1,
        "request.completed",
        (),
        exc_info=None,
        extra={"request_id": "client.request-123_ok"},
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "request_id" not in payload


def test_json_formatter_does_not_promote_arbitrary_safe_looking_text():
    record = logging.getLogger("third.party").makeRecord(
        "third.party",
        logging.WARNING,
        __file__,
        1,
        "opaquecredentialthatlookslikeaneventname",
        (),
        exc_info=None,
        extra={"endpoint": "opaquecredentialthatlookslikeasourceidentifier"},
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "log.event"
    assert payload["logger"] == "application"
    assert "endpoint" not in payload


def test_json_formatter_rejects_arbitrary_short_path_segments():
    record = logging.getLogger("illinicover.request").makeRecord(
        "illinicover.request",
        logging.INFO,
        __file__,
        1,
        "request.completed",
        (),
        exc_info=None,
        extra={"endpoint": "/not-a-route/alice"},
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "endpoint" not in payload
