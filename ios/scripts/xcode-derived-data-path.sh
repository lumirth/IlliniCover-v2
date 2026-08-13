#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
repo_root=$(CDPATH= cd -- "$ios_dir/.." && pwd)

mode=${ILLINICOVER_XCODE_CACHE_MODE:-shared}
case "$mode" in
  shared)
    if [ -n "${ILLINICOVER_XCODE_CACHE_SUFFIX:-}" ]; then
      echo "ILLINICOVER_XCODE_CACHE_SUFFIX requires ILLINICOVER_XCODE_CACHE_MODE=diagnostic" >&2
      exit 64
    fi
    printf '%s\n' "$repo_root/.local/DerivedData"
    ;;
  diagnostic)
    suffix=${ILLINICOVER_XCODE_CACHE_SUFFIX:-}
    case "$suffix" in
      ''|*[!A-Za-z0-9._-]*)
        echo "Diagnostic Xcode cache requires a safe ILLINICOVER_XCODE_CACHE_SUFFIX" >&2
        exit 64
        ;;
    esac
    printf '%s\n' "$repo_root/.local/DerivedData-diagnostic-$suffix"
    ;;
  *)
    echo "ILLINICOVER_XCODE_CACHE_MODE must be shared or diagnostic" >&2
    exit 64
    ;;
esac
