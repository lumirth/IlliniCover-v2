import Observation
import SwiftUI

enum VenueSort: String, CaseIterable, Identifiable {
    case openDate = "Open Date (Old-New)"
    case name = "Name (A-Z)"
    case lowestReports = "Lowest by Reports"
    case recentlyUpdated = "Recently Updated"
    var id: String { rawValue }
}

enum DealsSort: String, CaseIterable, Identifiable {
    case openDate = "Open Date (Old-New)"
    case name = "Name (A-Z)"
    case lowestReports = "Lowest by Reports"
    case recentlyUpdated = "Recently Updated"
    var id: String { rawValue }
}

enum ThemePreference: String, CaseIterable, Identifiable {
    case system = "System"
    case light = "Light"
    case dark = "Dark"
    var id: String { rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

enum PendingPrivacyTransition: String, Sendable {
    case none
    case deleteAccount
    case rotateGuest
}

@MainActor
@Observable
final class AppSettings {
    private let defaults: UserDefaults

    var sort: VenueSort { didSet { defaults.set(sort.rawValue, forKey: "venue-sort") } }
    var dealsSort: DealsSort { didSet { defaults.set(dealsSort.rawValue, forKey: "deals-sort") } }
    var theme: ThemePreference { didSet { defaults.set(theme.rawValue, forKey: "theme") } }
    var includeLocation: Bool { didSet { defaults.set(includeLocation, forKey: "include-location") } }
    var onboardingComplete: Bool { didSet { defaults.set(onboardingComplete, forKey: "onboarding-complete") } }
    var pendingPrivacyTransition: PendingPrivacyTransition {
        didSet { defaults.set(pendingPrivacyTransition.rawValue, forKey: "pending-privacy-transition") }
    }
    var pendingPrivacyRequestID: String? {
        didSet { defaults.set(pendingPrivacyRequestID, forKey: "pending-privacy-request-id") }
    }
    var pendingInstallationRequestID: String? {
        didSet { defaults.set(pendingInstallationRequestID, forKey: "pending-installation-request-id") }
    }
    var pendingLinkRequestID: String? {
        didSet { defaults.set(pendingLinkRequestID, forKey: "pending-link-request-id") }
    }

    var privacyPurgePending: Bool { pendingPrivacyTransition != .none }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        sort = VenueSort(rawValue: defaults.string(forKey: "venue-sort") ?? "") ?? .openDate
        dealsSort = DealsSort(rawValue: defaults.string(forKey: "deals-sort") ?? "") ?? .openDate
        theme = ThemePreference(rawValue: defaults.string(forKey: "theme") ?? "") ?? .system
        includeLocation = defaults.object(forKey: "include-location") as? Bool ?? false
        onboardingComplete = defaults.bool(forKey: "onboarding-complete")
        pendingPrivacyTransition = PendingPrivacyTransition(
            rawValue: defaults.string(forKey: "pending-privacy-transition") ?? ""
        ) ?? (defaults.bool(forKey: "privacy-purge-pending") ? .rotateGuest : .none)
        pendingPrivacyRequestID = defaults.string(forKey: "pending-privacy-request-id")
        pendingInstallationRequestID = defaults.string(forKey: "pending-installation-request-id")
        pendingLinkRequestID = defaults.string(forKey: "pending-link-request-id")
    }

    func reset() {
        sort = .openDate
        dealsSort = .openDate
        theme = .system
        includeLocation = false
    }
}
