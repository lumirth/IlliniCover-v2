import Observation
import SwiftUI

enum AppRoute: Hashable {
    case venue(String)
    case coverHistory(String)
    case estimate(String)
    case timeMachine(String)
    case handbook
    case handbookPage(String)
    case account
    case premium
    case privacy
    case support
}

struct CoverReportSeed: Identifiable, Hashable {
    let id: UUID
    let venue: Venue
    let decision: CoverDecision
    let interaction: CoverInteraction
    let initialPriceCents: Int?

    init(venue: Venue, decision: CoverDecision, interaction: CoverInteraction, initialPriceCents: Int?) {
        id = UUID()
        self.venue = venue
        self.decision = decision
        self.interaction = interaction
        self.initialPriceCents = initialPriceCents
    }
}

enum DealComposerMode: String, Hashable {
    case add
    case confirm
    case deny
    case review

    var title: String {
        switch self {
        case .add: "Add Deal"
        case .confirm: "Confirm"
        case .deny: "Wrong"
        case .review: "Review"
        }
    }
}

struct DealComposerSeed: Identifiable, Hashable {
    let id: UUID
    let venue: Venue
    let mode: DealComposerMode
    let deal: Deal?
    let suggestions: [Deal]
    /// The service night of the slate that opened this editor. A composer left
    /// open across Chicago's 05:00 rollover must not silently report the old
    /// offer as evidence for the new night.
    let serviceDate: String

    init(
        venue: Venue,
        mode: DealComposerMode,
        deal: Deal?,
        suggestions: [Deal] = [],
        serviceDate: String = ServiceNight.currentServiceDate
    ) {
        id = UUID()
        self.venue = venue
        self.mode = mode
        self.deal = deal
        self.suggestions = suggestions
        self.serviceDate = serviceDate
    }
}

enum AppSheet: Identifiable {
    case coverReport(CoverReportSeed)
    case dealComposer(DealComposerSeed)
    case signIn
    case locationOnboarding

    var id: String {
        switch self {
        case .coverReport(let seed): "cover-\(seed.id.uuidString)"
        case .dealComposer(let seed): "deal-\(seed.id.uuidString)"
        case .signIn: "sign-in"
        case .locationOnboarding: "location"
        }
    }
}

@MainActor
@Observable
final class AppRouter {
    var path: [AppRoute] = []
    var sheet: AppSheet?

    func push(_ route: AppRoute) { path.append(route) }
}

enum AppDeepLink {
    static func venueID(from url: URL) -> String? {
        guard url.scheme?.lowercased() == "illinicover" else { return nil }
        var components = url.pathComponents.filter { $0 != "/" }
        if let host = url.host, !host.isEmpty { components.insert(host, at: 0) }
        guard components.count == 2, components[0].lowercased() == "bar" else { return nil }
        let venueID = components[1].trimmingCharacters(in: .whitespacesAndNewlines)
        return venueID.isEmpty ? nil : venueID
    }

    static func venueURL(id: String) -> URL {
        var components = URLComponents()
        components.scheme = "illinicover"
        components.host = "bar"
        components.path = "/\(id)"
        return components.url!
    }

    static var barsURL: URL { URL(string: "illinicover://bars")! }
}

struct TabNavigationRoot<Content: View>: View {
    let router: AppRouter
    @ViewBuilder let content: () -> Content

    var body: some View {
        @Bindable var router = router
        NavigationStack(path: $router.path) {
            content()
                .navigationDestination(for: AppRoute.self) { route in
                    AppDestination(route: route)
                }
        }
        .environment(router)
        .sheet(item: $router.sheet) { sheet in
            AppSheetView(sheet: sheet)
                .environment(router)
        }
    }
}

private struct AppDestination: View {
    let route: AppRoute

    @ViewBuilder
    var body: some View {
        switch route {
        case .venue(let id): VenueDetailView(venueID: id)
        case .coverHistory(let id): CoverHistoryView(venueID: id)
        case .estimate(let id): EstimateDetailView(venueID: id)
        case .timeMachine(let id): TimeMachineView(venueID: id)
        case .handbook: HandbookListView()
        case .handbookPage(let slug): HandbookPageView(slug: slug)
        case .account: AccountView()
        case .premium: PremiumView()
        case .privacy: PrivacyDataView()
        case .support: SupportView()
        }
    }
}

private struct AppSheetView: View {
    let sheet: AppSheet

    @ViewBuilder
    var body: some View {
        switch sheet {
        case .coverReport(let seed): CoverReportView(seed: seed)
        case .dealComposer(let seed): DealComposerView(seed: seed)
        case .signIn: NavigationStack { SignInFlow() }
        case .locationOnboarding: LocationOnboardingView(isPresentedModally: true)
        }
    }
}
