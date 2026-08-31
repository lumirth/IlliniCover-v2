import Observation
import SwiftUI

@MainActor @Observable
final class DealsModel {
    var slate: DealsResponse?
    var loading = true
    var offline = false
    var error: String?

    func load(_ environment: AppEnvironment) async {
        if slate == nil, let cached = try? await environment.database.cached(DealsResponse.self, key: "deals") {
            slate = cached.0; offline = true; loading = false
        }
        await refresh(environment)
    }

    func refresh(_ environment: AppEnvironment) async {
        do { let value = try await environment.api.deals(); slate = value; try await environment.database.cache(value, key: "deals"); offline = false; error = nil }
        catch { offline = slate != nil; self.error = slate == nil ? error.localizedDescription : nil }
        loading = false
    }

    func venues(_ sort: ListSort) -> [VenueDeals] {
        (slate?.venues ?? []).sorted { left, right in
            if left.deals.isEmpty != right.deals.isEmpty { return !left.deals.isEmpty }
            switch sort {
            case .name: return left.venue.name < right.venue.name
            case .price: return (left.deals.compactMap(\.priceCents).min() ?? .max) < (right.deals.compactMap(\.priceCents).min() ?? .max)
            case .recent: return (left.deals.compactMap(\.latestActivityAt).max() ?? .distantPast) > (right.deals.compactMap(\.latestActivityAt).max() ?? .distantPast)
            }
        }
    }

    func report(_ deal: Deal, venue: Venue, action: DealEvidenceAction, environment: AppEnvironment) async -> SubmissionOutcome {
        let now = Date.now, id = UUID().uuidString
        let location = environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil
        return await environment.submitDeal(.init(
            action: action,
            clientPlatform: "ios",
            entryPoint: "deals",
            location: location,
            observedAt: now,
            serviceDateLocal: ServiceNight.serviceDate(containing: now),
            submissionId: id,
            submittedDealShape: nil,
            targetDealId: deal.id,
            vantagePoint: .unknown,
            venueId: venue.id
        ))
    }
}

struct DealsView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model = DealsModel()
    @State private var composer: DealComposerSeed?
    @State private var notice: String?

    var body: some View {
        Group {
            if model.loading && model.slate == nil { ProgressView("Loading tonight’s deals…") }
            else if let error = model.error, model.slate == nil { ContentUnavailableView("Deals unavailable", systemImage: "tag.slash", description: Text(error)) }
            else {
                List {
                    if model.offline { OfflineBanner(text: "Showing saved deals. Pull to refresh when online.") }
                    ForEach(model.venues(environment.settings.sort)) { venue in
                        Section(venue.venue.name) {
                            ForEach(venue.deals) { deal in
                                DealRow(deal: deal)
                                    .contextMenu {
                                        Button("Confirm available", systemImage: "checkmark") { report(deal, venue.venue, .confirmPresent) }
                                        Button("Report unavailable", systemImage: "xmark") { report(deal, venue.venue, .denyPresent) }
                                        Button("Correct details", systemImage: "pencil") { composer = .init(venue: venue.venue, action: .correct, deal: deal) }
                                    }
                            }
                            Button("Add missing deal", systemImage: "plus") { composer = .init(venue: venue.venue, action: .addMissing) }
                        }
                    }
                }.refreshable { await model.refresh(environment) }
            }
        }
        .navigationTitle("Deals")
        .toolbar { Menu { Picker("Sort", selection: Bindable(environment.settings).sort) { ForEach(ListSort.allCases) { Text($0.rawValue).tag($0) } } } label: { Label("Sort deals", systemImage: "arrow.up.arrow.down") } }
        .overlay(alignment: .top) { if let notice { Text(notice).padding(9).background(.regularMaterial, in: .capsule) } }
        .task { await model.load(environment) }
        .sheet(item: $composer) { DealComposerView(seed: $0) }
    }

    private func report(_ deal: Deal, _ venue: Venue, _ action: DealEvidenceAction) {
        Task {
            let outcome = await model.report(deal, venue: venue, action: action, environment: environment)
            notice = outcome.dealNotice(for: action)
            outcome == .failed ? Haptics.warning() : Haptics.success()
            if outcome == .sent { await model.refresh(environment) }
        }
    }
}

private struct DealRow: View {
    let deal: Deal
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack { Text(deal.displayName).font(.headline); Spacer(); Text(deal.priceText).bold() }
            Text([deal.servingText, deal.timingText].compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
        }.accessibilityElement(children: .combine).accessibilityIdentifier("deal-offer")
    }
}
