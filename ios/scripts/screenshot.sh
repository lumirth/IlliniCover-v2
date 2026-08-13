#!/bin/sh
set -eu

: "${ILLINICOVER_SIMULATOR_UDID:?Set ILLINICOVER_SIMULATOR_UDID to the dedicated simulator UDID}"
: "${1:?Pass a screenshot name}"
case "$1" in
  *[!A-Za-z0-9._-]*) echo "error: screenshot name may use letters, numbers, dot, underscore, and dash" >&2; exit 1 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
output_dir="$repo_root/.artifacts/ui"
mkdir -p "$output_dir"
output="$output_dir/$1.png"
xcrun simctl io "$ILLINICOVER_SIMULATOR_UDID" screenshot "$output"
echo "$output"
