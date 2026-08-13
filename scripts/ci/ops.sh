#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

while IFS= read -r script; do
  bash -n "$script"
done < <(find scripts ops -type f -name '*.sh' -print | sort)

if command -v shellcheck >/dev/null 2>&1; then
  # The local toolchain may provide shellcheck; CI installs it on ubuntu.
  shell_scripts=()
  while IFS= read -r script; do
    shell_scripts+=("$script")
  done < <(find scripts ops -type f -name '*.sh' -print | sort)
  shellcheck -x "${shell_scripts[@]}"
else
  echo "shellcheck is not installed; bash syntax still validated"
fi

uv run python scripts/ci/validate_ops.py
if command -v actionlint >/dev/null 2>&1; then
  actionlint .github/workflows/*.yml
else
  echo "actionlint is not installed; semantic workflow validation still ran"
fi
PYTHONPATH=scripts/ci uv run python -m unittest \
  scripts/ci/test_classify_changes.py \
  scripts/ci/test_classify_migrations.py \
  scripts/ci/test_migration_evidence.py \
  scripts/ci/test_local_config.py
PYTHONPATH=scripts/release uv run python -m unittest \
  scripts/release/test_artifact_image_cleanup.py \
  scripts/release/test_classify_runtime_changes.py \
  scripts/release/test_cloud_run_release_state.py \
  scripts/release/test_deploy_scheduler_cutover.py \
  scripts/release/test_secret_version_guard.py \
  scripts/release/test_service_release.py \
  scripts/release/test_update_preview_bundle.py \
  scripts/release/test_verify_release_resource.py \
  scripts/release/test_verify_scheduler.py

scripts/local/compose.sh config --quiet
