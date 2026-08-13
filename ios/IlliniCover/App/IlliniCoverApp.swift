import SwiftUI

/// SwiftUI may recreate the `App` value while installing its `@State`
/// storage. Keep process-scoped dependencies out of that value initializer so
/// a fresh scene cannot create a second installation actor or monitoring SDK.
@MainActor
private enum AppProcessDependencies {
    static let environment: AppEnvironment = {
        ErrorMonitoring.start(configuration: .current)
        return AppEnvironment.make()
    }()
}

@main
struct IlliniCoverApp: App {
    @State private var environment = AppProcessDependencies.environment

    var body: some Scene {
        WindowGroup {
            AppRootView()
                .environment(environment)
                .preferredColorScheme(environment.settings.theme.colorScheme)
                .tint(ICTheme.accent)
        }
    }
}

private struct AppRootView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            // Local onboarding and cached product surfaces are presentation
            // authority. Remote installation/account recovery continues in
            // the task below and gates mutations, but never holds a returning
            // user behind a network-dependent launch screen.
            if environment.acceptanceResetPending {
                if let notice = environment.globalNotice {
                    ContentUnavailableView(
                        "Acceptance reset failed",
                        systemImage: "lock.trianglebadge.exclamationmark",
                        description: Text(notice)
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(ICTheme.background)
                    .accessibilityIdentifier("live-acceptance-reset-failed-gate")
                } else {
                    ProgressView("Resetting local acceptance state…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(ICTheme.background)
                        .accessibilityIdentifier("live-acceptance-reset-gate")
                }
            } else if environment.settings.pendingPrivacyTransition != .none {
                PrivacyTransitionGateView()
            } else if !environment.settings.onboardingComplete {
                OnboardingFlow()
            } else {
                AppShell()
            }
        }
        .task { await environment.bootstrap() }
        .onOpenURL { url in
            environment.pendingDeepLinkVenueID = AppDeepLink.venueID(from: url)
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await environment.didEnterForeground() }
        }
    }
}

private struct PrivacyTransitionGateView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var isRetrying = false
    @State private var showSignIn = false

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "clock.badge.exclamationmark")
                .font(.system(size: 42, weight: .semibold))
                .foregroundStyle(.orange)
            Text(environment.hasPendingAccountDeletion ? "Account deletion pending" : "Guest deletion pending")
                .font(.title2.bold())
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("privacy-transition-gate")
            Text("Private local data stays hidden and reporting is paused while IlliniCover confirms this deletion.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button(isRetrying ? "Checking…" : "Check Deletion Status") {
                isRetrying = true
                Task {
                    await environment.didEnterForeground()
                    isRetrying = false
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isRetrying || environment.isBootstrapping)
            .accessibilityIdentifier("privacy-transition-recovery")
            if environment.hasPendingAccountDeletion {
                Button("Sign In to Finish Deletion") { showSignIn = true }
                    .buttonStyle(.bordered)
                    .disabled(isRetrying)
                    .accessibilityIdentifier("privacy-transition-sign-in")
                Text("Sign in only to the same account that requested deletion. A different account will never be deleted.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            if let notice = environment.globalNotice {
                Text(notice).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ICTheme.background)
        .sheet(isPresented: $showSignIn) { NavigationStack { SignInFlow() } }
    }
}

private enum AppTab: Hashable {
    case bars, deals, settings
}

private struct AppShell: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var selectedTab: AppTab = .bars
    @State private var barsRouter = AppRouter()
    @State private var dealsRouter = AppRouter()
    @State private var settingsRouter = AppRouter()

    var body: some View {
        TabView(selection: $selectedTab) {
            TabNavigationRoot(router: barsRouter) { CoverBoardView() }
                .tabItem { Label("Bars", systemImage: "building.2") }
                .tag(AppTab.bars)
                .accessibilityIdentifier("bars-tab")

            TabNavigationRoot(router: dealsRouter) { DealsView() }
                .tabItem { Label("Deals", systemImage: "tag") }
                .tag(AppTab.deals)
                .accessibilityIdentifier("deals-tab")

            TabNavigationRoot(router: settingsRouter) { SettingsView() }
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(AppTab.settings)
                .accessibilityIdentifier("settings-tab")
        }
        .overlay(alignment: .top) {
            if let notice = environment.globalNotice {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "info.circle.fill").foregroundStyle(ICTheme.accent)
                    Text(notice).font(.footnote).frame(maxWidth: .infinity, alignment: .leading)
                    Button {
                        environment.globalNotice = nil
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                    }
                    .accessibilityLabel("Dismiss notice")
                }
                .padding(12)
                .background(.regularMaterial, in: .rect(cornerRadius: 16, style: .continuous))
                .shadow(color: .black.opacity(0.12), radius: 8, y: 3)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("global-notice")
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .overlay(alignment: .topTrailing) {
            if let marker = environment.configuration.environmentMarker {
                Text(marker)
                    .font(.caption2.weight(.bold))
                    .tracking(0.8)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.yellow, in: .capsule)
                    .padding(.top, environment.globalNotice == nil ? 8 : 64)
                    .padding(.trailing, 12)
                    .allowsHitTesting(false)
                    .accessibilityLabel("\(marker.capitalized) environment")
                    .accessibilityIdentifier("environment-marker")
            }
        }
        .onChange(of: environment.pendingDeepLinkVenueID, initial: true) { _, venueID in
            guard let venueID else { return }
            selectedTab = .bars
            barsRouter.path = [.venue(venueID)]
            environment.pendingDeepLinkVenueID = nil
        }
        .animation(.snappy, value: environment.globalNotice)
    }
}
