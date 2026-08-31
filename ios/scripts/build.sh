#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
scheme=${ILLINICOVER_IOS_SCHEME:-IlliniCover Local}
derived_data_path=$("$script_dir/xcode-derived-data-path.sh")
exec xcodebuild \
  -project "$ios_dir/IlliniCover.xcodeproj" \
  -scheme "$scheme" \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$derived_data_path" \
  ARCHS=arm64 \
  CODE_SIGNING_ALLOWED=NO \
  build
