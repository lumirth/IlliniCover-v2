#!/bin/sh
set -eu

: "${ILLINICOVER_SIMULATOR_UDID:?Set ILLINICOVER_SIMULATOR_UDID to the dedicated simulator UDID}"
state=$(xcrun simctl list devices | grep "$ILLINICOVER_SIMULATOR_UDID" || true)
test -n "$state" || { echo "error: simulator UDID not found" >&2; exit 1; }
case "$state" in
  *Booted*) ;;
  *) xcrun simctl boot "$ILLINICOVER_SIMULATOR_UDID" ;;
esac
xcrun simctl bootstatus "$ILLINICOVER_SIMULATOR_UDID" -b
