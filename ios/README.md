# Native iOS client

IlliniCover is one SwiftUI application targeting iOS 18. The checked-in
`IlliniCover.xcodeproj` is the sole project authority; there is no XcodeGen
manifest or generated Swift API client.

The small Codable types in `IlliniCover/API/Models.swift` are simultaneously
the HTTP, local-cache, and product data representation. `LiveAPIClient` uses
Foundation `URLSession` against the sole unversioned `/api/` surface. OpenAPI
remains the backend's published contract, but adding a generator, generated
source tree, mapping layer, or fixture backend would recreate authorities the
app deliberately removed.

```sh
cd ios
./scripts/build.sh
./scripts/test.sh
```

The app has two configurations:

- Local uses the side-by-side development bundle, loopback HTTP, and the
  RevenueCat Test Store.
- Production uses the production bundle, exact Cloud Run origin, and an Apple
  RevenueCat public SDK key.

Both use the same live client. Tests that need product data run against local
Django/PostgreSQL; the app does not bundle JSON fixtures or ship a fake API.

Keychain holds only installation, account-session, and transient email-code
credentials. GRDB holds cached responses and the exact offline submission
outbox. The local database has one current pre-alpha schema and is recreated
on schema mismatch without touching Keychain credentials.

`IC_API_BASE_URL`, `IC_REVENUECAT_API_KEY`, `IC_SENTRY_DSN`,
`IC_SUPPORT_EMAIL`, and `IC_PRIVACY_POLICY_URL` are supplied through the two
checked-in xcconfig/Info.plist pairs. Monitoring is disabled when its DSN is
blank and applies a strict no-PII event allowlist when enabled.
