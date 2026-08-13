#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"
scripts/ci/backend.sh
scripts/ci/data.sh
scripts/ci/fixtures.sh --check
scripts/ci/ops.sh

echo 'Local backend, OpenAPI, data, fixture, and operations gates passed.'
echo 'GitHub workflow path policy and the Apple/Xcode Cloud lane remain separate authorities.'
