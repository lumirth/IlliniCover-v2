#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

mode="${1:---check}"
settings="config.settings.fixtures"

mkdir -p .local/visual-acceptance
uv run python server/manage.py migrate --noinput --settings="$settings" >/dev/null

case "$mode" in
  --write)
    exec uv run python server/manage.py export_api_fixtures \
      --settings="$settings" --output api/fixtures
    ;;
  --check)
    temporary="$(mktemp -d)"
    trap 'rm -rf -- "$temporary"' EXIT
    uv run python server/manage.py export_api_fixtures \
      --settings="$settings" --output "$temporary"
    diff -ru api/fixtures "$temporary"
    ;;
  *)
    echo "Usage: scripts/ci/fixtures.sh [--check|--write]" >&2
    exit 2
    ;;
esac
