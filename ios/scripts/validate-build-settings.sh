#!/bin/sh
set -eu

fail() {
  echo "error: $1" >&2
  exit 1
}

test "${DEVELOPMENT_TEAM:-}" = "Y74N5FFSEJ" || fail "IlliniCover must use Apple Developer team Y74N5FFSEJ"

case "${CONFIGURATION:-}" in
  Local)
    test "${PRODUCT_BUNDLE_IDENTIFIER:-}" = "com.illinicover.app.dev" || fail "Local must use com.illinicover.app.dev"
    printf '%s' "${IC_API_BASE_URL:-}" | grep -Eq '^http://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?$' || fail "Local must use loopback HTTP"
    printf '%s' "${IC_REVENUECAT_API_KEY:-}" | grep -Eq '^test_[A-Za-z0-9]+$' || fail "Local must use RevenueCat Test Store"
    ;;
  Preview)
    test "${PRODUCT_BUNDLE_IDENTIFIER:-}" = "com.illinicover.app.dev" || fail "Preview must use com.illinicover.app.dev"
    test "${IC_API_BASE_URL:-}" = "https://illinicover-preview-1068900473446.us-east5.run.app" || fail "Preview origin is outside the allowlist"
    printf '%s' "${IC_REVENUECAT_API_KEY:-}" | grep -Eq '^test_[A-Za-z0-9]+$' || fail "Preview must use RevenueCat Test Store"
    ;;
  Production)
    test "${PRODUCT_BUNDLE_IDENTIFIER:-}" = "com.illinicover.app" || fail "Production must use com.illinicover.app"
    test "${IC_API_BASE_URL:-}" = "https://illinicover-api-1068900473446.us-east5.run.app" || fail "Production origin is outside the allowlist"
    printf '%s' "${IC_REVENUECAT_API_KEY:-}" | grep -Eq '^appl_[A-Za-z0-9]{14,}$' || fail "Production requires an injected Apple RevenueCat public SDK key"
    printf '%s' "${IC_CODE_REVISION:-}" | grep -Eq '^[0-9a-f]{40}$' || fail "Production requires the exact deployed 40-character Git commit SHA"
    if test -n "${IC_SENTRY_DSN:-}"; then
      printf '%s' "$IC_SENTRY_DSN" | grep -Eq '^https://[^[:space:]@]+@[^[:space:]]+/[0-9]+$' || fail "Production Sentry DSN is malformed"
    fi
    if test -n "${IC_SUPPORT_EMAIL:-}"; then
      printf '%s' "$IC_SUPPORT_EMAIL" | grep -Eq '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' || fail "Production support email is malformed"
    fi
    ;;
  *) fail "Unknown IlliniCover build configuration: ${CONFIGURATION:-missing}" ;;
esac
