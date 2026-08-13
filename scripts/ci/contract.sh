#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

cd "$repository"
uv run python server/manage.py export_client_openapi \
  --settings=config.settings.test --output "$temporary/openapi.json" >/dev/null
diff -u api/openapi.json "$temporary/openapi.json"
