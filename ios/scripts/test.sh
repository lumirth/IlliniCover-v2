#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
repo_root=$(CDPATH='' cd -- "$ios_dir/.." && pwd)
: "${ILLINICOVER_SIMULATOR_UDID:?Set ILLINICOVER_SIMULATOR_UDID to the dedicated simulator UDID}"
scheme=${ILLINICOVER_IOS_SCHEME:-IlliniCover Local}
plan=${ILLINICOVER_TEST_PLAN:-Fast}
derived_data_path=$("$script_dir/xcode-derived-data-path.sh")
receipt_id=$(date -u +%Y%m%dT%H%M%SZ)-$$
result_bundle_path="$repo_root/.artifacts/ios/${plan}-${receipt_id}.xcresult"
mkdir -p "$repo_root/.artifacts/ios"

exec xcodebuild \
  -project "$ios_dir/IlliniCover.xcodeproj" \
  -scheme "$scheme" \
  -testPlan "$plan" \
  -destination "platform=iOS Simulator,id=${ILLINICOVER_SIMULATOR_UDID}" \
  -derivedDataPath "$derived_data_path" \
  -resultBundlePath "$result_bundle_path" \
  ARCHS=arm64 \
  test
