#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

uv run ruff check server scripts tests
uv run python server/manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run python server/manage.py check --settings=config.settings.test
PYTHONPATH=scripts/release uv run python -m unittest \
  scripts/release/test_source_revision.py \
  scripts/release/test_deploy_scheduler_cutover.py \
  scripts/release/test_service_release.py \
  scripts/release/test_update_preview_bundle.py \
  scripts/release/test_verify_scheduler.py
PYTHONPATH=scripts/ci uv run python -m unittest \
  scripts/ci/test_classify_changes.py \
  scripts/ci/test_classify_migrations.py \
  scripts/ci/test_migration_evidence.py \
  scripts/ci/test_local_config.py
scripts/ci/contract.sh
uv run pytest -q server
