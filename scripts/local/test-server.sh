#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

# shellcheck disable=SC1091
source scripts/local/environment.sh

scripts/local/compose.sh up -d --wait postgres
export DJANGO_SETTINGS_MODULE=config.settings.ci
uv run python server/manage.py migrate --noinput
exec uv run pytest -q server
