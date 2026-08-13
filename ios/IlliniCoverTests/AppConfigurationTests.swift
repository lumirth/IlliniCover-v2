import Foundation
import Testing
import UIKit
@testable import IlliniCover

@Suite("App configuration")
struct AppConfigurationTests {
    @Test("Local and Preview have separate identity, settings, and database namespaces despite sharing a bundle")
    func environmentStorageIsolation() {
        let local = AppStorageIdentity.resolve(
            bundleIdentifier: AppConfiguration.developmentBundleIdentifier,
            deploymentEnvironment: .local,
            runtimeMode: .standard
        )
        let preview = AppStorageIdentity.resolve(
            bundleIdentifier: AppConfiguration.developmentBundleIdentifier,
            deploymentEnvironment: .preview,
            runtimeMode: .standard
        )
        #expect(local != preview)
        #expect(local.credentialService != preview.credentialService)
        #expect(local.defaultsSuite != preview.defaultsSuite)
        #expect(local.databaseNamespace != preview.databaseNamespace)
        #expect(local.databaseNamespace == "local")
        #expect(preview.databaseNamespace == "preview")
    }

    @Test("Venue deep links round trip through the established app scheme")
    func venueDeepLinks() throws {
        let id = "11111111-1111-4111-8111-111111111111"
        let url = AppDeepLink.venueURL(id: id)
        #expect(url.absoluteString == "illinicover://bar/\(id)")
        #expect(AppDeepLink.venueID(from: url) == id)
        #expect(AppDeepLink.venueID(from: URL(string: "illinicover:///bar/\(id)")!) == id)
        #expect(AppDeepLink.venueID(from: URL(string: "https://example.com/bar/\(id)")!) == nil)
    }

    @Test("Venue sharing selects image mode and retains an exact link fallback")
    func venueSharePayloadBoundary() {
        let venue = Venue(
            id: "11111111-1111-4111-8111-111111111111",
            slug: "kams",
            name: "KAMS",
            address: "102 E Green St",
            openedYear: 1933
        )
        let descriptor = VenueShareDescriptor(venue: venue)
        #expect(descriptor.message == "KAMS on IlliniCover")
        #expect(descriptor.fallbackText == "KAMS on IlliniCover\nillinicover://bar/11111111-1111-4111-8111-111111111111")
        #expect(VenueSharePayload(descriptor: descriptor, image: nil).mode == .link)
        #expect(VenueSharePayload(descriptor: descriptor, image: UIImage()).mode == .image)
    }

    @Test("Board sharing selects branded image mode and retains the Bars deep-link fallback")
    func boardSharePayloadBoundary() {
        let fallback = BoardSharePayload(image: nil)
        #expect(AppDeepLink.barsURL.absoluteString == "illinicover://bars")
        #expect(fallback.mode == .link)
        #expect(fallback.fallbackText == "Bars on IlliniCover\nillinicover://bars")
        #expect(BoardSharePayload(image: UIImage()).mode == .image)
    }

    @Test("Live acceptance is Debug-only and distinct from Preview UI testing")
    func runtimeModes() {
        #expect(AppRuntimeMode.resolve(arguments: ["app", "-uiTesting", "-liveAcceptance"]) == .uiTesting)
#if DEBUG
        #expect(AppRuntimeMode.resolve(arguments: ["app", "-liveAcceptance"]) == .liveAcceptance)
#else
        #expect(AppRuntimeMode.resolve(arguments: ["app", "-liveAcceptance"]) == .standard)
#endif
        #expect(AppRuntimeMode.resolve(arguments: ["app"]) == .standard)
    }

    @Test("Live acceptance refuses every non-loopback API origin")
    func liveAcceptanceLoopbackGate() {
        for value in ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"] {
            #expect(AppRuntimeMode.permitsLiveAcceptanceBaseURL(URL(string: value)!))
        }
        for value in [
            "https://illinicover-api.example.run.app",
            "http://localhost.example.com:8000",
            "http://127.0.0.1.example.com:8000",
            "file:///tmp/fixture.json",
        ] {
            #expect(!AppRuntimeMode.permitsLiveAcceptanceBaseURL(URL(string: value)!))
        }
    }

    @Test("The hosted app bundle uses the v2 marketing and build versions")
    func bundleVersion() {
        #expect(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String == "2.0.0")
        #expect(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String == "1")
    }

    @Test("Blank external service values remain disabled")
    func blankValuesAreDisabled() throws {
        let configuration = try AppConfiguration.validated(infoDictionary: [
            "ICAPIBaseURL": "http://127.0.0.1:8000",
            "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
            "ICSentryDSN": "",
            "ICEnvironment": "local",
            "ICCodeRevision": "abc123",
            "ICSupportEmail": "\n",
            "ICPrivacyPolicyURL": "",
        ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)

        #expect(configuration.revenueCatAPIKey == AppConfiguration.testStoreAPIKey)
        #expect(configuration.sentryDSN == nil)
        #expect(configuration.supportEmail == nil)
        #expect(configuration.privacyPolicyURL == nil)
        #expect(configuration.environment == "local")
        #expect(configuration.environmentMarker == "LOCAL")
        #expect(configuration.codeRevision == "abc123")
        #expect(!ErrorMonitoring.isEnabled(configuration: configuration))
    }

    @Test("Configured monitoring and support are parsed without secrets in source")
    func configuredServicesAreEnabled() throws {
        let configuration = try AppConfiguration.validated(infoDictionary: [
            "ICAPIBaseURL": "http://localhost:8000",
            "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
            "ICSentryDSN": "https://public@example.ingest.sentry.io/1",
            "ICEnvironment": "local",
            "ICCodeRevision": "deadbeef",
            "ICSupportEmail": "support@example.invalid",
            "ICPrivacyPolicyURL": "https://example.invalid/privacy",
        ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)

        #expect(ErrorMonitoring.isEnabled(configuration: configuration))
        #expect(configuration.supportEmail == "support@example.invalid")
        #expect(configuration.privacyPolicyURL?.absoluteString == "https://example.invalid/privacy")
    }

    @Test("Local, preview, and production configurations are exact fail-closed boundaries")
    func environmentBoundaries() throws {
        let local = try AppConfiguration.validated(infoDictionary: [
            "ICAPIBaseURL": "http://[::1]:8000",
            "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
            "ICEnvironment": "local",
            "ICCodeRevision": "local",
        ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)
        #expect(local.deploymentEnvironment == .local)

        let preview = try AppConfiguration.validated(infoDictionary: [
            "ICAPIBaseURL": AppConfiguration.previewAPIOrigin.absoluteString,
            "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
            "ICEnvironment": "preview",
            "ICCodeRevision": "preview",
        ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)
        #expect(preview.environmentMarker == "PREVIEW")

        let productionRevision = String(repeating: "a", count: 40)
        let production = try AppConfiguration.validated(infoDictionary: [
            "ICAPIBaseURL": AppConfiguration.productionAPIOrigin.absoluteString,
            "ICRevenueCatAPIKey": "appl_1a2b3c4d5e6f7h",
            "ICEnvironment": "production",
            "ICCodeRevision": productionRevision,
        ], bundleIdentifier: AppConfiguration.productionBundleIdentifier)
        #expect(production.environmentMarker == nil)
        #expect(production.codeRevision == productionRevision)
    }

    @Test("Missing, malformed, cross-environment, and Test Store production values are refused")
    func invalidConfigurationsAreRefused() {
        #expect(throws: AppConfigurationError.self) {
            _ = try AppConfiguration.validated(
                infoDictionary: ["ICEnvironment": "local"],
                bundleIdentifier: AppConfiguration.developmentBundleIdentifier
            )
        }
        #expect(throws: AppConfigurationError.self) {
            _ = try AppConfiguration.validated(infoDictionary: [
                "ICAPIBaseURL": "://not-a-url",
                "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
                "ICEnvironment": "local",
            ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)
        }
        #expect(throws: AppConfigurationError.self) {
            _ = try AppConfiguration.validated(infoDictionary: [
                "ICAPIBaseURL": AppConfiguration.productionAPIOrigin.absoluteString,
                "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
                "ICEnvironment": "local",
            ], bundleIdentifier: AppConfiguration.developmentBundleIdentifier)
        }
        #expect(throws: AppConfigurationError.self) {
            _ = try AppConfiguration.validated(infoDictionary: [
                "ICAPIBaseURL": AppConfiguration.productionAPIOrigin.absoluteString,
                "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
                "ICEnvironment": "production",
                "ICCodeRevision": String(repeating: "a", count: 40),
            ], bundleIdentifier: AppConfiguration.productionBundleIdentifier)
        }
        #expect(throws: AppConfigurationError.self) {
            _ = try AppConfiguration.validated(infoDictionary: [
                "ICAPIBaseURL": AppConfiguration.previewAPIOrigin.absoluteString,
                "ICRevenueCatAPIKey": AppConfiguration.testStoreAPIKey,
                "ICEnvironment": "preview",
            ], bundleIdentifier: AppConfiguration.productionBundleIdentifier)
        }
        for key in ["foo", "goog_1a2b3c4d5e6f7h", "mac_1a2b3c4d5e6f7h", "appl_short"] {
            #expect(throws: AppConfigurationError.invalidRevenueCatKey(environment: "production")) {
                _ = try AppConfiguration.validated(infoDictionary: [
                    "ICAPIBaseURL": AppConfiguration.productionAPIOrigin.absoluteString,
                    "ICRevenueCatAPIKey": key,
                    "ICEnvironment": "production",
                    "ICCodeRevision": String(repeating: "a", count: 40),
                ], bundleIdentifier: AppConfiguration.productionBundleIdentifier)
            }
        }
        for revision in [
            "",
            String(repeating: "a", count: 39),
            String(repeating: "a", count: 41),
            String(repeating: "A", count: 40),
            "src-" + String(repeating: "a", count: 64),
        ] {
            #expect(throws: AppConfigurationError.invalidCodeRevision) {
                _ = try AppConfiguration.validated(infoDictionary: [
                    "ICAPIBaseURL": AppConfiguration.productionAPIOrigin.absoluteString,
                    "ICRevenueCatAPIKey": "appl_1a2b3c4d5e6f7h",
                    "ICEnvironment": "production",
                    "ICCodeRevision": revision,
                ], bundleIdentifier: AppConfiguration.productionBundleIdentifier)
            }
        }
    }
}
