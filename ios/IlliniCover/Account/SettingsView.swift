import CoreLocation
import SwiftUI

struct SettingsView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @State private var showResetAlert = false
    @State private var isRetryingSubmissions = false
    @State private var showDiscardFailedAlert = false

    var body: some View {
        @Bindable var settings = environment.settings
        Form {
            Section {
                Button { router.push(.account) } label: {
                    HStack(spacing: 12) {
                        Circle()
                            .fill(ICTheme.accent.opacity(0.16))
                            .frame(width: 42, height: 42)
                            .overlay(Text(initials).font(.headline).foregroundStyle(ICTheme.accent))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(environment.hasPendingAccountDeletion ? "Deletion Pending" : (environment.account?.firstName ?? "Account"))
                                .font(.headline).foregroundStyle(.primary)
                            Text(environment.hasPendingAccountDeletion ? "Waiting for server confirmation" : (environment.account?.email ?? "Guest · Sign in for Blue"))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption.bold()).foregroundStyle(.tertiary)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityHint("Open account settings")
            }

            Section("IlliniCover Blue") {
                Button { router.push(.premium) } label: {
                    LabeledContent {
                        Text(environment.premium ? "Active" : "View options")
                    } label: {
                        Label("IlliniCover Blue", systemImage: "clock.arrow.circlepath")
                    }
                }
                .foregroundStyle(.primary)
                .accessibilityIdentifier("illinicover-blue-settings")
                Button { router.push(.handbook) } label: {
                    Label("Handbook", systemImage: "book.closed")
                }
                .foregroundStyle(.primary)
                Button { router.push(.privacy) } label: {
                    Label("Privacy & Data", systemImage: "hand.raised")
                }
                .foregroundStyle(.primary)
                Button { router.push(.support) } label: {
                    Label("Support", systemImage: "questionmark.bubble")
                }
                .foregroundStyle(.primary)
            }

            Section("Preferences") {
                Picker("Sort bars", selection: $settings.sort) {
                    ForEach(VenueSort.allCases) { Text($0.rawValue).tag($0) }
                }
                Picker("Appearance", selection: $settings.theme) {
                    ForEach(ThemePreference.allCases) { Text($0.rawValue).tag($0) }
                }
                Toggle("Include location with reports", isOn: Binding(
                    get: { settings.includeLocation },
                    set: { updateLocation($0) }
                ))
                LabeledContent("Location access", value: locationStatus)
                    .foregroundStyle(.secondary)
            }

            Section("Setup") {
                Button("Show Onboarding Again") { settings.onboardingComplete = false }
                Button("Reset Preferences", role: .destructive) { showResetAlert = true }
            }

            if environment.outboxStatus.queued > 0 || environment.outboxStatus.failed > 0 {
                Section {
                    if environment.outboxStatus.queued > 0 {
                        LabeledContent(
                            "Waiting to send",
                            value: environment.outboxStatus.queued.formatted()
                        )
                    }
                    if environment.outboxStatus.failed > 0 {
                        LabeledContent(
                            "Needs retry",
                            value: environment.outboxStatus.failed.formatted()
                        )
                        .foregroundStyle(ICTheme.wrong)
                        ForEach(environment.failedSubmissions.prefix(5)) { failure in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(failure.kind == .cover ? "Cover report" : "Deal report")
                                    .font(.subheadline.weight(.semibold))
                                Text("\(failure.observedAt.formatted(date: .abbreviated, time: .shortened)) · \(failure.failureDescription)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if environment.failedSubmissions.contains(where: \FailedSubmissionSummary.canRetryUnchanged) {
                            Button(isRetryingSubmissions ? "Retrying…" : "Retry Temporary Failures") {
                                retryFailedSubmissions()
                            }
                            .disabled(isRetryingSubmissions)
                        }
                        Button("Discard Failed Reports", role: .destructive) {
                            showDiscardFailedAlert = true
                        }
                    }
                } header: {
                    Text("Pending Reports")
                } footer: {
                    Text("Queued reports keep their original observation time. Validation failures cannot be fixed by sending the same data again; discard them, then create a corrected report from the current bar or deal slate.")
                }
            }

            Section {
                VStack(alignment: .leading, spacing: 4) {
                    Text("IlliniCover v2").font(.subheadline.weight(.semibold))
                    Text("Live reports are observations, not official venue prices. Exact location and private identity details are never shown publicly.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Settings")
        .alert("Reset preferences?", isPresented: $showResetAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Reset", role: .destructive) { settings.reset() }
        } message: {
            Text("This restores sorting, appearance, and report-location preferences.")
        }
        .alert("Discard failed reports?", isPresented: $showDiscardFailedAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Discard", role: .destructive) {
                Task { await environment.discardFailedSubmissions(); Haptics.success() }
            }
        } message: {
            Text("This removes the saved failed copies from this device. You can submit corrected reports from the current Bars or Deals screen.")
        }
        .task { await environment.refreshFailedSubmissions() }
    }

    private var initials: String {
        if let name = environment.account?.firstName, let first = name.first { return String(first).uppercased() }
        if let first = environment.account?.email.first { return String(first).uppercased() }
        return "G"
    }

    private var locationStatus: String {
        switch environment.location.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: "Allowed"
        case .denied, .restricted: "Not allowed"
        case .notDetermined: "Not requested"
        @unknown default: "Unknown"
        }
    }

    private func updateLocation(_ enabled: Bool) {
        if !enabled { environment.settings.includeLocation = false; return }
        Task {
            let status = await environment.location.requestAuthorization()
            environment.settings.includeLocation = status == .authorizedAlways || status == .authorizedWhenInUse
            if !environment.settings.includeLocation,
               let url = URL(string: UIApplication.openSettingsURLString) {
                await UIApplication.shared.open(url)
            }
        }
    }

    private func retryFailedSubmissions() {
        guard !isRetryingSubmissions else { return }
        isRetryingSubmissions = true
        Task {
            await environment.retryFailedSubmissions()
            isRetryingSubmissions = false
            if environment.outboxStatus.failed == 0 { Haptics.success() }
            else { Haptics.warning() }
        }
    }
}

private extension FailedSubmissionSummary {
    var failureDescription: String {
        switch failureCode {
        case "unauthorized": "Sign-in or installation changed"
        case "installation_link_conflict": "Device account link conflict"
        case "privacy_transition_unconfirmed": "Deletion is still pending"
        case "offline": "Network unavailable"
        case "configuration": "Server configuration unavailable"
        case let code where code.hasPrefix("server_4"): "Server rejected the saved details"
        case let code where code.hasPrefix("server_5"): "Temporary server problem"
        default: "Could not be delivered"
        }
    }
}

struct PrivacyDataView: View {
    @Environment(AppEnvironment.self) private var environment

    var body: some View {
        List {
            Section("Optional location") {
                Text("If you turn location on for reports, IlliniCover collects latitude, longitude, horizontal accuracy, and the observation time only when you intentionally submit a report.")
                Text("Location is optional. Reports without it are accepted neutrally; absence does not count against a report.")
            }
            Section("How it is used") {
                Text("The production evidence assessment uses venue distance and reported accuracy, plus frozen impossible-movement and rapid-pattern signals. Raw coordinates are never displayed publicly.")
                Text("IlliniCover does not continuously track your device and does not request background location access.")
            }
            Section("Report and interaction provenance") {
                Text("A report stores the venue, reported value, observation time, outside/inside context, and the product state you saw: displayed decision, source, price, whether a value was prefilled or touched, the entry point, app version, and client platform.")
                Text("IlliniCover uses this interaction path only to assess evidence quality, explain and reproduce decisions, and diagnose submission behavior. It is not used for cross-app tracking or advertising.")
            }
            Section("Network and retention") {
                Text("IlliniCover does not retain raw IP addresses in report records. Automatic Cloud Run request logs can include a requester address, but IlliniCover configures the project log router to exclude those logs from storage, so they are not retained in the project's Cloud Logging buckets. The server retains a keyed network verifier only to detect abuse. Submitted latitude, longitude, accuracy, and observation time are preserved so evidence can be recalculated as distance, accuracy, impossible-travel, and proximity rules improve.")
                Text("Those raw observations remain associated with the account or guest installation until that account is deleted or the guest installation is rotated. They are never shown publicly.")
                Text("After erasure, deidentified accepted observation values, evidence provenance, and derived assessment snapshots may remain. Account, installation actor, exact location, network verifier, session, entitlement, and provider metadata are removed.")
            }
            Section("Your controls") {
                Text("You can stop including location at any time in Settings. Deleting an account clears local queued reports and cached private state. Guest rotation clears the same local data and replaces the installation identity.")
            }
            Section("Minimal error monitoring") {
                Text("When a monitoring address is configured, IlliniCover sends only the app release, environment, platform, generalized error type, and scrubbed stack frames needed to correlate crashes. Monitoring is disabled when that address is not configured.")
                Text("It excludes request and report bodies, headers, cookies, URL queries, exception messages, local variables, breadcrumbs, screenshots, view hierarchy, identity, performance traces, and network traces before transmission.")
            }
            Section("Providers and support") {
                Text("Google Cloud Run and Neon host the app and database; RevenueCat processes purchase and entitlement state; and configured Sentry receives only the minimal error receipt above. They are limited to operating, securing, supporting, or billing for IlliniCover and must provide protection equivalent to these commitments.")
                Text("When support is configured, Report a Problem opens a mail draft containing your issue, app and iOS versions, and any venue, approximate time, decision ID, or request ID you choose. You review it before sending. The support mailbox retains correspondence only as long as needed to resolve and document the request, subject to legal or security preservation requirements.")
            }
            if let policyURL = environment.configuration.privacyPolicyURL {
                Section {
                    Link("Open Published Privacy Policy", destination: policyURL)
                }
            }
        }
        .navigationTitle("Privacy & Data")
        .navigationBarTitleDisplayMode(.large)
    }
}
