import SwiftUI

@MainActor private let processEnvironment: AppEnvironment = {
    ErrorMonitoring.start(configuration: .current)
    return .make()
}()

@main
struct IlliniCoverApp: App {
    @State private var environment = processEnvironment
    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(environment)
                .preferredColorScheme(environment.settings.theme.colorScheme)
                .tint(ICTheme.accent)
        }
    }
}

private struct RootView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if environment.settings.onboardingComplete { AppShell() }
            else { OnboardingFlow() }
        }
        .task { await environment.bootstrap() }
        .onOpenURL { environment.pendingDeepLinkVenueID = DeepLink.venueID($0) }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Task { await environment.didEnterForeground() } } }
    }
}

private struct AppShell: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var selectedTab = 0
    @State private var venuePath: [String] = []

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack(path: $venuePath) {
                CoverBoardView()
                    .navigationDestination(for: String.self) { VenueDetailView(venueID: $0) }
            }
            .tabItem { Label("Bars", systemImage: "building.2") }.tag(0)
            NavigationStack { DealsView() }
                .tabItem { Label("Deals", systemImage: "tag") }.tag(1)
            NavigationStack { SettingsView() }
                .tabItem { Label("Settings", systemImage: "gearshape") }.tag(2)
        }
        .overlay(alignment: .top) {
            if let notice = environment.globalNotice {
                HStack { Text(notice).font(.footnote); Spacer(); Button("Dismiss") { environment.globalNotice = nil } }
                    .padding(12).background(.regularMaterial, in: .rect(cornerRadius: 14)).padding()
                    .accessibilityIdentifier("global-notice")
            }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            if let marker = environment.configuration.environmentMarker {
                Text(marker)
                    .font(.caption2.bold())
                    .dynamicTypeSize(...DynamicTypeSize.large)
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .frame(maxWidth: .infinity)
                    .background(.yellow.opacity(0.9))
                    .accessibilityLabel("Local development environment")
            }
        }
        .onChange(of: environment.pendingDeepLinkVenueID, initial: true) { _, id in
            guard let id else { return }
            selectedTab = 0; venuePath = [id]; environment.pendingDeepLinkVenueID = nil
        }
    }
}

enum DeepLink {
    static func venueID(_ url: URL) -> String? {
        guard url.scheme == "illinicover", url.host == "venue" else { return nil }
        return url.pathComponents.dropFirst().first
    }
    static func venueURL(_ id: String) -> URL { URL(string: "illinicover://venue/\(id)")! }
}
