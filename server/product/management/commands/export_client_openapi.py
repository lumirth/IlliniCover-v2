import json
from pathlib import Path

from config.api import api
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Export the client OpenAPI contract."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, **options):
        output = Path(options["output"])
        schema = api.get_openapi_schema(path_prefix="/api")
        output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
