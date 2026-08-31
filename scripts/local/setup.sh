#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

if [[ ! -f .env.local ]]; then
  cp .env.example .env.local
  echo "Created .env.local with disposable local-only defaults."
fi

uv sync --frozen
scripts/local/compose.sh up --detach --wait postgres
scripts/local/manage.sh migrate --noinput
scripts/local/manage.sh bootstrap

echo "Local PostgreSQL is healthy, migrated, and deterministically seeded."
