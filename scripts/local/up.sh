#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"
scripts/local/compose.sh up --detach --wait postgres
exec scripts/local/manage.sh runserver 127.0.0.1:8000
