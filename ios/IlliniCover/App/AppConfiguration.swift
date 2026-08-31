import Foundation

enum AppDeploymentEnvironment: String, Sendable { case local, production, test }

struct AppConfiguration: Sendable {
    static let developmentBundle = "com.illinicover.app.dev"
    static let productionBundle = "com.illinicover.app"
    static let testStoreKey = "test_iNDNDGHzWoIeKSjnCzimZCaymqr"
    static let productionOrigin = URL(string: "https://illinicover-api-1068900473446.us-east5.run.app")!

    let apiBaseURL: URL
    let revenueCatAPIKey: String?
    let sentryDSN: String?
    let deployment: AppDeploymentEnvironment
    let supportEmail: String?
    let privacyPolicyURL: URL?

    static var current: Self {
        do { return try validated(Bundle.main.infoDictionary ?? [:], bundle: Bundle.main.bundleIdentifier) }
        catch { fatalError("Invalid IlliniCover configuration: \(error.localizedDescription)") }
    }

    static func validated(_ info: [String: Any], bundle: String?) throws -> Self {
        guard let rawURL = (info["ICAPIBaseURL"] as? String)?.nilIfBlank,
              let url = URL(string: rawURL), url.host != nil else { throw ConfigurationError("ICAPIBaseURL") }
        guard let rawEnvironment = info["ICEnvironment"] as? String,
              let deployment = AppDeploymentEnvironment(rawValue: rawEnvironment), deployment != .test,
              let bundle else { throw ConfigurationError("ICEnvironment") }
        let key = (info["ICRevenueCatAPIKey"] as? String)?.nilIfBlank
        switch deployment {
        case .local:
            guard bundle == developmentBundle, url.scheme == "http", ["localhost", "127.0.0.1", "::1"].contains(url.host) else {
                throw ConfigurationError("local origin or bundle")
            }
        case .production:
            guard bundle == productionBundle, origin(url) == origin(productionOrigin), key?.hasPrefix("appl_") == true else {
                throw ConfigurationError("production origin, bundle, or RevenueCat key")
            }
        case .test: throw ConfigurationError("ICEnvironment")
        }
        return Self(
            apiBaseURL: url,
            revenueCatAPIKey: key,
            sentryDSN: (info["ICSentryDSN"] as? String)?.nilIfBlank,
            deployment: deployment,
            supportEmail: (info["ICSupportEmail"] as? String)?.nilIfBlank,
            privacyPolicyURL: (info["ICPrivacyPolicyURL"] as? String).flatMap(URL.init(string:))
        )
    }

    var environmentMarker: String? { deployment == .local ? "LOCAL" : nil }

    private static func origin(_ url: URL) -> String {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.path = ""; components?.query = nil; components?.fragment = nil
        return components?.url?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ?? ""
    }
}

struct ConfigurationError: LocalizedError {
    let field: String
    init(_ field: String) { self.field = field }
    var errorDescription: String? { "Invalid app configuration: \(field)." }
}
