#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
test -f "$ios_dir/IlliniCover.xcodeproj/project.pbxproj"
test -f "$ios_dir/TestPlans/Fast.xctestplan"
test -f "$ios_dir/IlliniCover.xcodeproj/xcshareddata/xcschemes/IlliniCover.xcscheme"
"$ios_dir/scripts/validate-environments.sh"
