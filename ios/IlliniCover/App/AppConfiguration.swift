import Foundation

enum AppDeploymentEnvironment: String, Sendable {
    case local
    case preview
    case production
    case test
}

enum AppConfigurationError: LocalizedError, Equatable {
    case missingValue(String)
    case invalidURL(String)
    case invalidEnvironment(String)
    case bundleMismatch(environment: String, bundle: String)
    case originMismatch(environment: String, origin: String)
    case invalidRevenueCatKey(environment: String)
    case invalidCodeRevision

    var errorDescription: String? {
        switch self {
        case .missingValue(let key): return "Missing required app configuration: \(key)."
        case .invalidURL(let value): return "Invalid IlliniCover API URL: \(value)."
        case .invalidEnvironment(let value): return "Unknown IlliniCover environment: \(value)."
        case .bundleMismatch(let environment, let bundle):
            return "Bundle \(bundle) is not permitted for the \(environment) environment."
        case .originMismatch(let environment, let origin):
            return "API origin \(origin) is not permitted for the \(environment) environment."
        case .invalidRevenueCatKey(let environment):
            return "The \(environment) RevenueCat public SDK key is missing or belongs to the wrong store."
        case .invalidCodeRevision: return "Production requires the exact deployed 40-character Git commit SHA."
        }
    }
}

struct AppConfiguration: Sendable {
    static let developmentBundleIdentifier = "com.illinicover.app.dev"
    static let productionBundleIdentifier = "com.illinicover.app"
    static let testStoreAPIKey = "test_iNDNDGHzWoIeKSjnCzimZCaymqr"
    static let productionAPIOrigin = URL(string: "https://illinicover-api-1068900473446.us-east5.run.app")!
    static let previewAPIOrigin = URL(string: "https://illinicover-preview-1068900473446.us-east5.run.app")!

    let apiBaseURL: URL
    let revenueCatAPIKey: String?
    let sentryDSN: String?
    let environment: String
    let codeRevision: String
    let supportEmail: String?
    let privacyPolicyURL: URL?

    init(
        apiBaseURL: URL,
        revenueCatAPIKey: String?,
        sentryDSN: String? = nil,
        environment: String = "test",
        codeRevision: String = "test",
        supportEmail: String? = nil,
        privacyPolicyURL: URL? = nil
    ) {
        self.apiBaseURL = apiBaseURL
        self.revenueCatAPIKey = revenueCatAPIKey
        self.sentryDSN = sentryDSN?.nilIfBlank
        self.environment = environment
        self.codeRevision = codeRevision
        self.supportEmail = supportEmail?.nilIfBlank
        self.privacyPolicyURL = privacyPolicyURL
    }

    static var current: AppConfiguration {
        do {
            return try validated(
                infoDictionary: Bundle.main.infoDictionary ?? [:],
                bundleIdentifier: Bundle.main.bundleIdentifier
            )
        } catch {
            fatalError("Invalid IlliniCover configuration: \(error.localizedDescription)")
        }
    }

    static func validated(
        infoDictionary dictionary: [String: Any],
        bundleIdentifier: String?
    ) throws -> AppConfiguration {
        guard let rawURL = (dictionary["ICAPIBaseURL"] as? String)?.nilIfBlank else {
            throw AppConfigurationError.missingValue("ICAPIBaseURL")
        }
        guard let apiURL = URL(string: rawURL), apiURL.scheme != nil, apiURL.host != nil else {
            throw AppConfigurationError.invalidURL(rawURL)
        }
        guard let rawEnvironment = (dictionary["ICEnvironment"] as? String)?.nilIfBlank,
              let deployment = AppDeploymentEnvironment(rawValue: rawEnvironment),
              deployment != .test else {
            throw AppConfigurationError.invalidEnvironment((dictionary["ICEnvironment"] as? String) ?? "")
        }
        guard let bundleIdentifier = bundleIdentifier?.nilIfBlank else {
            throw AppConfigurationError.missingValue("CFBundleIdentifier")
        }

        let rawRevenueCat = (dictionary["ICRevenueCatAPIKey"] as? String)?.nilIfBlank
        switch deployment {
        case .local:
            guard bundleIdentifier == developmentBundleIdentifier else {
                throw AppConfigurationError.bundleMismatch(environment: rawEnvironment, bundle: bundleIdentifier)
            }
            guard isLoopbackHTTP(apiURL) else {
                throw AppConfigurationError.originMismatch(environment: rawEnvironment, origin: apiURL.absoluteString)
            }
            guard rawRevenueCat == testStoreAPIKey else {
                throw AppConfigurationError.invalidRevenueCatKey(environment: rawEnvironment)
            }
        case .preview:
            guard bundleIdentifier == developmentBundleIdentifier else {
                throw AppConfigurationError.bundleMismatch(environment: rawEnvironment, bundle: bundleIdentifier)
            }
            guard normalizedOrigin(apiURL) == normalizedOrigin(previewAPIOrigin) else {
                throw AppConfigurationError.originMismatch(environment: rawEnvironment, origin: apiURL.absoluteString)
            }
            guard rawRevenueCat == testStoreAPIKey else {
                throw AppConfigurationError.invalidRevenueCatKey(environment: rawEnvironment)
            }
        case .production:
            guard bundleIdentifier == productionBundleIdentifier else {
                throw AppConfigurationError.bundleMismatch(environment: rawEnvironment, bundle: bundleIdentifier)
            }
            guard normalizedOrigin(apiURL) == normalizedOrigin(productionAPIOrigin) else {
                throw AppConfigurationError.originMismatch(environment: rawEnvironment, origin: apiURL.absoluteString)
            }
            guard let rawRevenueCat,
                  rawRevenueCat.range(
                    of: #"^appl_[A-Za-z0-9]{14,}$"#,
                    options: .regularExpression
                  ) != nil else {
                throw AppConfigurationError.invalidRevenueCatKey(environment: rawEnvironment)
            }
            let revision = (dictionary["ICCodeRevision"] as? String)?.nilIfBlank ?? ""
            guard revision.range(of: #"^[0-9a-f]{40}$"#, options: .regularExpression) != nil else {
                throw AppConfigurationError.invalidCodeRevision
            }
        case .test:
            assertionFailure("Test configuration is never loaded from an application bundle")
        }

        return AppConfiguration(
            apiBaseURL: apiURL,
            revenueCatAPIKey: rawRevenueCat?.nilIfBlank,
            sentryDSN: dictionary["ICSentryDSN"] as? String,
            environment: rawEnvironment,
            codeRevision: (dictionary["ICCodeRevision"] as? String)?.nilIfBlank ?? "unknown",
            supportEmail: dictionary["ICSupportEmail"] as? String,
            privacyPolicyURL: (dictionary["ICPrivacyPolicyURL"] as? String)?.nilIfBlank.flatMap(URL.init(string:))
        )
    }

    var deploymentEnvironment: AppDeploymentEnvironment {
        AppDeploymentEnvironment(rawValue: environment) ?? .test
    }

    var environmentMarker: String? {
        switch deploymentEnvironment {
        case .local: "LOCAL"
        case .preview: "PREVIEW"
        case .production, .test: nil
        }
    }

    var releaseIdentifier: String {
        let bundle = Bundle.main.bundleIdentifier ?? "com.illinicover.app.v2"
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
        return "\(bundle)@\(version)+\(build)-\(codeRevision)"
    }

    private static func isLoopbackHTTP(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "http", let host = url.host?.lowercased() else { return false }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }

    private static func normalizedOrigin(_ url: URL) -> String {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.path = ""
        components?.query = nil
        components?.fragment = nil
        return components?.url?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ?? ""
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
