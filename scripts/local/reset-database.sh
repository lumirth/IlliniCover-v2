#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"
echo "Recreating only the illinicover-local PostgreSQL Compose volume."
scripts/local/compose.sh down --volumes
scripts/local/compose.sh up --detach --wait postgres
scripts/local/manage.sh migrate --noinput
scripts/local/manage.sh bootstrap
