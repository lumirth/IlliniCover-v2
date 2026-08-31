import CoreLocation
import SwiftUI

struct SettingsView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var reset = false
    @State private var discard = false

    var body: some View {
        @Bindable var settings = environment.settings
        Form {
            Section {
                NavigationLink { AccountView() } label: {
                    LabeledContent(environment.account?.displayName.nilIfBlank ?? "Account", value: environment.account?.email ?? "Guest")
                }
                NavigationLink("IlliniCover Blue") { PremiumView() }
                NavigationLink("Handbook") { HandbookListView() }
                NavigationLink("Privacy & Data") { PrivacyDataView() }
                NavigationLink("Support") { SupportView() }
            }
            Section("Preferences") {
                Picker("Sort bars and deals", selection: $settings.sort) { ForEach(ListSort.allCases) { Text($0.rawValue).tag($0) } }
                Picker("Appearance", selection: $settings.theme) { ForEach(ThemePreference.allCases) { Text($0.rawValue.capitalized).tag($0) } }
                Toggle("Include location with reports", isOn: $settings.includeLocation)
                LabeledContent("Location access", value: locationStatus)
            }
            Section("Setup") {
                Button("Show Onboarding Again") { settings.onboardingComplete = false }
                Button("Reset Preferences", role: .destructive) { reset = true }
            }
            if environment.outboxStatus.queued + environment.outboxStatus.failed > 0 {
                Section("Pending Reports") {
                    LabeledContent("Waiting to send", value: environment.outboxStatus.queued.formatted())
                    if environment.outboxStatus.failed > 0 {
                        LabeledContent("Server rejected", value: environment.outboxStatus.failed.formatted()).foregroundStyle(.red)
                        Button("Retry Failed Reports") { Task { await environment.retryFailedSubmissions() } }
                        Button("Discard Failed Reports", role: .destructive) { discard = true }
                    }
                }
            }
            Section { Text("Live reports are observations, not official venue prices. Exact location and private identity are never public.").font(.footnote).foregroundStyle(.secondary) }
        }
        .navigationTitle("Settings")
        .alert("Reset preferences?", isPresented: $reset) { Button("Cancel", role: .cancel) {}; Button("Reset", role: .destructive) { settings.reset() } }
        .alert("Discard failed reports?", isPresented: $discard) { Button("Cancel", role: .cancel) {}; Button("Discard", role: .destructive) { Task { await environment.discardFailedSubmissions() } } }
    }

    private var locationStatus: String {
        switch environment.location.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: "Allowed"
        case .denied, .restricted: "Not allowed"
        case .notDetermined: "Not requested"
        @unknown default: "Unknown"
        }
    }

}

struct PrivacyDataView: View {
    @Environment(AppEnvironment.self) private var environment
    var body: some View {
        List {
            Section("Optional location") {
                Text("Location is collected only when you intentionally submit a report with the setting enabled. IlliniCover never requests background tracking.")
                Text("Exact coordinates remain private and may be used to assess venue proximity, accuracy, and abuse patterns.")
            }
            Section("Reports") {
                Text("Reports preserve the value, observation time, interaction, and what the app displayed so the server can assess and reproduce its decision without a mutable receipt ID.")
                Text("Public results never expose account, installation, network, or exact-location data.")
            }
            Section("Deletion") {
                Text("Account deletion or guest rotation clears credentials, queued reports, local cache, exact location, and private attribution. Deidentified observations may remain.")
            }
            if let url = environment.configuration.privacyPolicyURL { Section { Link("Published Privacy Policy", destination: url) } }
        }.navigationTitle("Privacy & Data")
    }
}
