#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

scripts/local/compose.sh config --format json | python3 -c '
import json, sys
config = json.load(sys.stdin)
services = config.get("services", {})
volumes = config.get("volumes", {})
expected_volume = "illinicover-v2-local_postgres-data"
valid = (
    config.get("name") == "illinicover-v2-local"
    and set(services) == {"postgres"}
    and set(volumes) == {"postgres-data"}
    and volumes["postgres-data"].get("name") == expected_volume
    and len(services["postgres"].get("volumes", [])) == 1
    and services["postgres"]["volumes"][0].get("type") == "volume"
    and services["postgres"]["volumes"][0].get("source") == "postgres-data"
    and services["postgres"]["volumes"][0].get("target") == "/var/lib/postgresql"
)
raise SystemExit(0 if valid else 1)
'

echo "Resetting only the illinicover-v2-local PostgreSQL Compose volume."
scripts/local/compose.sh down --volumes
scripts/local/compose.sh up --detach --wait postgres
scripts/local/manage.sh migrate --noinput
scripts/local/manage.sh bootstrap_beta
