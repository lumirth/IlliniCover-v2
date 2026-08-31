import Observation
import SwiftUI

enum ListSort: String, CaseIterable, Identifiable {
    case name = "Name"
    case price = "Lowest price"
    case recent = "Recently updated"
    var id: Self { self }
}

enum ThemePreference: String, CaseIterable, Identifiable {
    case system, light, dark
    var id: Self { self }
    var colorScheme: ColorScheme? { self == .light ? .light : (self == .dark ? .dark : nil) }
}

@MainActor @Observable
final class AppSettings {
    private let defaults: UserDefaults
    var sort: ListSort { didSet { defaults.set(sort.rawValue, forKey: "sort") } }
    var theme: ThemePreference { didSet { defaults.set(theme.rawValue, forKey: "theme") } }
    var includeLocation: Bool { didSet { defaults.set(includeLocation, forKey: "location") } }
    var onboardingComplete: Bool { didSet { defaults.set(onboardingComplete, forKey: "onboarded") } }
    var accountDeletionUncertain: Bool { didSet { defaults.set(accountDeletionUncertain, forKey: "accountDeletionUncertain") } }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        sort = ListSort(rawValue: defaults.string(forKey: "sort") ?? "") ?? .name
        theme = ThemePreference(rawValue: defaults.string(forKey: "theme") ?? "") ?? .system
        includeLocation = defaults.bool(forKey: "location")
        onboardingComplete = defaults.bool(forKey: "onboarded")
        accountDeletionUncertain = defaults.bool(forKey: "accountDeletionUncertain")
    }

    func reset() {
        sort = .name
        theme = .system
        includeLocation = false
    }
}
