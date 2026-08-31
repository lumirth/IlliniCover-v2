#!/bin/sh
set -eu

fail() { echo "error: $1" >&2; exit 1; }

test "${DEVELOPMENT_TEAM:-}" = "Y74N5FFSEJ" || fail "unexpected Apple Developer team"
case "${CONFIGURATION:-}" in
  Local)
    test "${PRODUCT_BUNDLE_IDENTIFIER:-}" = "com.illinicover.app.dev" || fail "invalid Local bundle ID"
    printf '%s' "${IC_API_BASE_URL:-}" | grep -Eq '^http://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?$' || fail "Local API must be loopback HTTP"
    printf '%s' "${IC_REVENUECAT_API_KEY:-}" | grep -Eq '^test_[A-Za-z0-9]+$' || fail "Local must use RevenueCat Test Store"
    ;;
  Production)
    test "${PRODUCT_BUNDLE_IDENTIFIER:-}" = "com.illinicover.app" || fail "invalid Production bundle ID"
    test "${IC_API_BASE_URL:-}" = "https://illinicover-api-1068900473446.us-east5.run.app" || fail "Production API is outside the allowlist"
    printf '%s' "${IC_REVENUECAT_API_KEY:-}" | grep -Eq '^appl_[A-Za-z0-9]{14,}$' || fail "Production requires the Apple RevenueCat key"
    ;;
  *) fail "unknown build configuration: ${CONFIGURATION:-missing}" ;;
esac
