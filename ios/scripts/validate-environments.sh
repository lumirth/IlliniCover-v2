#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ios_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

require_line() {
  file=$1
  pattern=$2
  message=$3
  if ! grep -Eq "$pattern" "$file"; then
    echo "error: $message" >&2
    exit 1
  fi
}

local_config="$ios_dir/Config/Local.xcconfig"
preview_config="$ios_dir/Config/Preview.xcconfig"
production_config="$ios_dir/Config/Production.xcconfig"

require_line "$local_config" '^PRODUCT_BUNDLE_IDENTIFIER = com\.illinicover\.app\.dev$' "Local must use the development bundle"
require_line "$local_config" '^IC_API_BASE_URL = http:/\$\(\)/(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?$' "Local must use an xcconfig-safe loopback HTTP API"
require_line "$local_config" '^IC_REVENUECAT_API_KEY = test_[A-Za-z0-9]+$' "Local must use RevenueCat Test Store"
require_line "$preview_config" '^PRODUCT_BUNDLE_IDENTIFIER = com\.illinicover\.app\.dev$' "Preview must use the development bundle"
require_line "$preview_config" '^IC_API_BASE_URL = https:/\$\(\)/illinicover-preview-1068900473446\.us-east5\.run\.app$' "Preview origin must match the shared service allowlist"
require_line "$preview_config" '^IC_REVENUECAT_API_KEY = test_[A-Za-z0-9]+$' "Preview must use RevenueCat Test Store"
require_line "$production_config" '^PRODUCT_BUNDLE_IDENTIFIER = com\.illinicover\.app$' "Production must use the production bundle"
require_line "$production_config" '^IC_API_BASE_URL = https:/\$\(\)/illinicover-api-1068900473446\.us-east5\.run\.app$' "Production origin must match the immutable allowlist"
require_line "$production_config" '^#include[?] "Production\.xcconfig\.local"$' "Production must retain the ignored local injection seam"
require_line "$production_config" '^IC_REVENUECAT_API_KEY = \$\(ILLINICOVER_REVENUECAT_APPLE_KEY\)$' "Production RevenueCat key must be injected"
require_line "$production_config" '^IC_CODE_REVISION = \$\(ILLINICOVER_CODE_REVISION\)$' "Production source revision must be injected"
require_line "$production_config" '^IC_SENTRY_DSN = \$\(ILLINICOVER_SENTRY_DSN\)$' "Production Sentry DSN must retain an injection seam"
require_line "$production_config" '^IC_SUPPORT_EMAIL = \$\(ILLINICOVER_SUPPORT_EMAIL\)$' "Production support email must retain an injection seam"

if grep -Eq 'NSAllowsArbitraryLoads|NSExceptionDomains' "$ios_dir/Config/Info-Preview.plist" "$ios_dir/Config/Info-Production.plist"; then
  echo "error: hosted configurations must not contain ATS exceptions" >&2
  exit 1
fi
require_line "$ios_dir/Config/Info-Local.plist" '<key>NSAllowsLocalNetworking</key>' "Local must scope ATS to local networking"

cache_helper="$ios_dir/scripts/xcode-derived-data-path.sh"
test -x "$cache_helper" || {
  echo "error: the canonical Xcode cache selector must be executable" >&2
  exit 1
}
require_line "$cache_helper" '\.local/DerivedData' "Local Xcode work must use the canonical .local/DerivedData cache"
for entrypoint in "$ios_dir/scripts/build.sh" "$ios_dir/scripts/test.sh" "$ios_dir/Makefile"; do
  require_line "$entrypoint" 'xcode-derived-data-path\.sh' "Every local Xcode entrypoint must use the canonical cache selector"
done
require_line "$ios_dir/scripts/build.sh" 'ARCHS=arm64' "Generic simulator builds must compile only the native arm64 architecture"
require_line "$ios_dir/scripts/test.sh" 'ARCHS=arm64' "Simulator tests must compile only the native arm64 architecture"
for invocation in $(grep -Rl 'xcodebuild' "$ios_dir/scripts" "$ios_dir/Makefile"); do
  case "$invocation" in
    "$ios_dir/scripts/build.sh"|"$ios_dir/scripts/test.sh"|"$ios_dir/scripts/validate-environments.sh"|"$ios_dir/Makefile") ;;
    *)
      echo "error: unexpected local xcodebuild invocation outside the canonical cache entrypoints: $invocation" >&2
      exit 1
      ;;
  esac
done

case "${CI_XCODE_SCHEME:-}" in
  IlliniCover)
    if ! printf '%s' "${ILLINICOVER_REVENUECAT_APPLE_KEY:-}" | grep -Eq '^appl_[A-Za-z0-9]{14,}$'; then
      echo "error: production requires an appl_ RevenueCat public SDK key" >&2
      exit 1
    fi
    if ! printf '%s' "${ILLINICOVER_CODE_REVISION:-}" | grep -Eq '^[0-9a-f]{40}$'; then
      echo "error: production requires ILLINICOVER_CODE_REVISION=<deployed 40-hex Git SHA>" >&2
      exit 1
    fi
    ;;
esac

echo "IlliniCover environment boundaries are valid."
