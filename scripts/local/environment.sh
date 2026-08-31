#!/usr/bin/env bash

# This file is sourced by repository-owned local tasks. It deliberately has no
# production defaults and never resolves provider credentials.
local_repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -f "${local_repository}/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${local_repository}/.env.local"
  set +a
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.development}"
export DATABASE_URL="${DATABASE_URL:-postgresql://illinicover_local:local-only@127.0.0.1:5432/illinicover}"
export DATABASE_URL_DIRECT="${DATABASE_URL_DIRECT:-$DATABASE_URL}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-local-development-only-not-for-deployment}"
export PUBLIC_API_ORIGIN="${PUBLIC_API_ORIGIN:-http://127.0.0.1:8000}"
