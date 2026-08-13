#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/local/environment.sh
source "${repository}/scripts/local/environment.sh"
cd "$repository"
exec uv run python server/manage.py "$@"
