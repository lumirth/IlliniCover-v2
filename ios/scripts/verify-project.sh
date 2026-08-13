#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project="$ios_dir/IlliniCover.xcodeproj"

if test -n "${XCODEGEN_BIN:-}"; then
  xcodegen_bin=$XCODEGEN_BIN
elif test -x /opt/homebrew/bin/xcodegen; then
  xcodegen_bin=/opt/homebrew/bin/xcodegen
else
  xcodegen_bin=$(command -v xcodegen || true)
fi
test -n "$xcodegen_bin" || {
  echo "error: xcodegen is required to verify the generated Xcode project" >&2
  exit 1
}
test -f "$project/project.pbxproj" || {
  echo "error: checked-in IlliniCover.xcodeproj is missing" >&2
  exit 1
}

receipt_dir=$(mktemp -d "${TMPDIR:-/tmp}/illinicover-project-check.XXXXXX")
cp "$project/project.pbxproj" "$receipt_dir/project.pbxproj"
cp -R "$project/xcshareddata/xcschemes" "$receipt_dir/xcschemes"

(cd "$ios_dir" && "$xcodegen_bin" generate --spec project.yml >/dev/null)
diff -u "$receipt_dir/project.pbxproj" "$project/project.pbxproj"
diff -ru "$receipt_dir/xcschemes" "$project/xcshareddata/xcschemes"
echo "Checked-in Xcode project matches ios/project.yml."
