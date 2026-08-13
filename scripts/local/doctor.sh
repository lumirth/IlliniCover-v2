#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

failed=0
for command in docker uv python3; do
  if command -v "$command" >/dev/null; then
    echo "ok: ${command}"
  else
    echo "missing: ${command}" >&2
    failed=1
  fi
done
if command -v docker >/dev/null; then
  if scripts/local/compose.sh config --quiet; then
    echo "ok: compose.yaml"
  else
    echo "invalid: compose.yaml" >&2
    failed=1
  fi
  scripts/local/compose.sh ps postgres || true
fi

exit "$failed"
