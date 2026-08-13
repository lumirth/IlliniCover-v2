import json

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_swift_compatible_contract_preserves_nullable_fields_and_cache_headers(tmp_path):
    output = tmp_path / "openapi.json"
    call_command("export_client_openapi", output=output, verbosity=0)
    schema = json.loads(output.read_text())

    assert schema["openapi"] == "3.0.3"
    cover_input = schema["components"]["schemas"]["CoverSubmissionSchema"]["properties"]
    assert cover_input["cover"]["nullable"] is True
    assert cover_input["location"]["nullable"] is True
    cover = schema["paths"]["/api/v2/cover"]["get"]
    assert any(parameter["name"] == "If-None-Match" for parameter in cover["parameters"])
    assert "ETag" in cover["responses"]["200"]["headers"]
    assert "304" in cover["responses"]
    for path in ("/api/v2/cover-submissions", "/api/v2/deal-evidence"):
        session_headers = [
            parameter
            for parameter in schema["paths"][path]["post"]["parameters"]
            if parameter["name"] == "X-Session-Token"
        ]
        assert session_headers == [
            {
                "in": "header",
                "name": "X-Session-Token",
                "required": False,
                "schema": {
                    "nullable": True,
                    "title": "X-Session-Token",
                    "type": "string",
                },
            }
        ]
    discount = schema["components"]["schemas"]["DealShapeSchema"]["properties"][
        "discountPercent"
    ]
    assert discount["minimum"] == 0
    assert discount["exclusiveMinimum"] is True


def test_checked_in_openapi_has_unique_operation_ids():
    schema = json.loads(open("api/openapi.json", encoding="utf-8").read())
    operation_ids = [
        operation["operationId"]
        for methods in schema["paths"].values()
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
