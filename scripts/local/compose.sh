#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
project_name="illinicover-local"
compose_file="${repository}/compose.yaml"

exec docker compose \
  --project-directory "$repository" \
  --project-name "$project_name" \
  --file "$compose_file" \
  "$@"
