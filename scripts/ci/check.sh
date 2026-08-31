#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
cd "$repository"

find ops scripts -name '*.sh' -exec bash -n {} +
find ios/scripts -name '*.sh' -exec sh -n {} +
mise exec -- actionlint .github/workflows/*.yml
uv run ruff check server ops
uv run mypy server ops/deployment/verify-cloud-run.py
uv run python server/manage.py check --settings=config.settings.ci
uv run python server/manage.py makemigrations --check --dry-run --settings=config.settings.ci
uv run python server/manage.py migrate --noinput --settings=config.settings.ci
uv run python server/manage.py bootstrap --settings=config.settings.ci
uv run python server/manage.py export_client_openapi \
  --settings=config.settings.ci --output "$temporary/openapi.json" >/dev/null
diff -u api/openapi.json "$temporary/openapi.json"
uv run pytest -q ops/deployment/test_deploy.py
uv run pytest -q server
