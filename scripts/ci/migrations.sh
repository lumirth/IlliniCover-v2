#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

settings="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
uv run python server/manage.py makemigrations --check --dry-run --settings="$settings"
uv run python server/manage.py migrate --plan --settings="$settings" >/dev/null

if [[ -n "${CHANGED_MIGRATIONS:-}" ]]; then
  changed_migrations=()
  while IFS= read -r changed_migration; do
    [[ -n "$changed_migration" ]] && changed_migrations+=("$changed_migration")
  done <<<"$CHANGED_MIGRATIONS"
  classifier_context=()
  if [[ -n "${MIGRATION_BASE_SHA:-}" ]]; then
    classifier_context=(--repository "$repository" --base "$MIGRATION_BASE_SHA")
  fi
  set +e
  python3 scripts/ci/classify_migrations.py \
    "${classifier_context[@]}" \
    "${changed_migrations[@]}"
  classification_status=$?
  set -e
  if (( classification_status == 10 )); then
    if [[ "${ALLOW_RISKY_MIGRATIONS:-false}" != "true" ]]; then
      echo "Likely destructive migration requires the destructive-migration-reviewed PR label and preview proof." >&2
      exit 10
    fi
    python3 scripts/ci/migration_evidence.py receipt
    echo "Risky migration marker and restore receipt acknowledged; CI separately verifies the exact preview run."
  elif (( classification_status != 0 )); then
    exit "$classification_status"
  fi
else
  echo "migration risk: no changed migration paths supplied"
fi
