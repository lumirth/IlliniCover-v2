#!/bin/sh
set -eu

: "${ILLINICOVER_SIMULATOR_UDID:?Set ILLINICOVER_SIMULATOR_UDID to the dedicated simulator UDID}"
bundle_id=com.illinicover.app.dev
xcrun simctl terminate "$ILLINICOVER_SIMULATOR_UDID" "$bundle_id" >/dev/null 2>&1 || true
if ! xcrun simctl launch "$ILLINICOVER_SIMULATOR_UDID" "$bundle_id" -resetLocalState; then
  echo "error: install IlliniCover Local before resetting its state" >&2
  exit 1
fi
echo "Reset requested inside IlliniCover.dev; the simulator itself was not erased."
