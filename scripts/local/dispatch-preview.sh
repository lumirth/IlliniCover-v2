#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repository"

if ! command -v gh >/dev/null; then
  echo "The GitHub CLI is required to dispatch preview.yml." >&2
  exit 2
fi
branch="$(git branch --show-current)"
if [[ -z "$branch" || "$branch" == "main" ]]; then
  echo "Preview dispatch requires a pushed non-main branch." >&2
  exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Preview dispatch requires committed work; push the branch first." >&2
  exit 2
fi

gh workflow run preview.yml --ref "$branch" --field ref="$branch"
echo "Dispatched the shared preview for ${branch}. Use 'gh run watch' for progress."
