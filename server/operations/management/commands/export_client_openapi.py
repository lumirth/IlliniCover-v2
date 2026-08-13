import json
from pathlib import Path

from config.api import api
from django.conf import settings
from django.core.management.base import BaseCommand


def openapi_30_nullable(value):
    if isinstance(value, list):
        return [openapi_30_nullable(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted = {key: openapi_30_nullable(item) for key, item in value.items() if key != "anyOf"}
    # JSON Schema/OpenAPI 3.1 encode exclusive bounds as numbers. OpenAPI 3.0
    # uses a boolean beside minimum/maximum.
    exclusive_minimum = value.get("exclusiveMinimum")
    if isinstance(exclusive_minimum, int | float) and not isinstance(exclusive_minimum, bool):
        converted["minimum"] = exclusive_minimum
        converted["exclusiveMinimum"] = True
    exclusive_maximum = value.get("exclusiveMaximum")
    if isinstance(exclusive_maximum, int | float) and not isinstance(exclusive_maximum, bool):
        converted["maximum"] = exclusive_maximum
        converted["exclusiveMaximum"] = True
    alternatives = value.get("anyOf")
    if isinstance(alternatives, list):
        non_null = [item for item in alternatives if item != {"type": "null"}]
        has_null = len(non_null) != len(alternatives)
        if has_null and len(non_null) == 1:
            schema = openapi_30_nullable(non_null[0])
            if "$ref" in schema:
                converted["allOf"] = [schema]
            else:
                converted.update(schema)
            converted["nullable"] = True
        else:
            converted["anyOf"] = openapi_30_nullable(alternatives)
    return converted


class Command(BaseCommand):
    help = "Export deterministic OpenAPI 3.0.3 for Swift OpenAPI Generator 1.13."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", default=str(settings.REPOSITORY_DIR / "api" / "openapi.json")
        )

    def handle(self, *args, **options):
        schema = openapi_30_nullable(dict(api.get_openapi_schema()))
        schema["openapi"] = "3.0.3"
        output = Path(options["output"])
        output.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(str(output))
