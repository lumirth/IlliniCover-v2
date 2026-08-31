import Observation
import SwiftUI

@MainActor @Observable
final class CoverBoardModel {
    var board: CoverBoardResponse?
    var loading = true
    var offline = false
    var error: String?
    private static let cacheKey = "cover"

    func load(_ environment: AppEnvironment) async {
        if board == nil, let cached = try? await environment.database.cached(CoverBoardResponse.self, key: Self.cacheKey) {
            board = cached.0; offline = true; loading = false
        }
        await refresh(environment)
    }

    func refresh(_ environment: AppEnvironment) async {
        do {
            let value = try await environment.api.coverBoard()
            board = value; offline = false; error = nil
            try await environment.database.cache(value, key: Self.cacheKey)
            await environment.outbox.drain()
        } catch { offline = board != nil; self.error = board == nil ? error.localizedDescription : nil }
        loading = false
    }

    func venues(sort: ListSort) -> [CoverVenueCard] {
        (board?.venues ?? []).sorted { left, right in
            switch sort {
            case .name: left.venue.name.localizedCaseInsensitiveCompare(right.venue.name) == .orderedAscending
            case .price: (left.cover?.price.floor ?? .max, left.venue.name) < (right.cover?.price.floor ?? .max, right.venue.name)
            case .recent: (left.latestActivityAt ?? .distantPast, left.venue.name) > (right.latestActivityAt ?? .distantPast, right.venue.name)
            }
        }
    }

    func quickReport(_ card: CoverVenueCard, environment: AppEnvironment) async -> SubmissionOutcome {
        guard let price = card.cover?.price.scalarCents else { return .failed }
        let now = Date.now, id = UUID().uuidString
        let location = environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil
        let request = CoverSubmissionRequest(
            clientPlatform: "ios",
            cover: .init(
                interaction: .quickConfirm,
                priceCents: price,
                pricePrefilled: true,
                priceTouched: false,
                displayedSource: card.cover?.source,
                displayedPriceKind: card.cover?.price.kind,
                displayedAmountCents: card.cover?.price.amountCents,
                displayedLowCents: card.cover?.price.lowCents,
                displayedHighCents: card.cover?.price.highCents
            ),
            entryPoint: "bar_card",
            location: location,
            observedAt: now,
            submissionId: id,
            vantagePoint: .unknown,
            venueId: card.venue.id,
            vibes: []
        )
        return await environment.submitCover(request)
    }
}

struct CoverBoardView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model = CoverBoardModel()
    @State private var report: CoverReportSeed?
    @State private var notice: String?

    var body: some View {
        Group {
            if model.loading && model.board == nil { ProgressView("Loading cover…") }
            else if let error = model.error, model.board == nil { ContentUnavailableView("Cover unavailable", systemImage: "wifi.exclamationmark", description: Text(error)) }
            else {
                List {
                    if model.offline { OfflineBanner(text: "Showing saved cover. Pull to refresh when online.") }
                    ForEach(model.venues(sort: environment.settings.sort)) { card in
                        NavigationLink(value: card.venue.id) { BarRow(card: card) }
                            .contextMenu {
                                Button("Report right price", systemImage: "checkmark") { quick(card) }
                                Button("Report another price", systemImage: "pencil") { report = .init(venue: card.venue, decision: card.cover, interaction: .correct) }
                                ShareLink(item: DeepLink.venueURL(card.venue.id))
                            }
                    }
                }
                .refreshable { await model.refresh(environment) }
            }
        }
        .navigationTitle("Bars")
        .toolbar {
            Menu {
                Picker("Sort", selection: Bindable(environment.settings).sort) { ForEach(ListSort.allCases) { Text($0.rawValue).tag($0) } }
            } label: { Label("Sort bars", systemImage: "arrow.up.arrow.down") }
        }
        .overlay(alignment: .top) { if let notice { Text(notice).padding(9).background(.regularMaterial, in: .capsule) } }
        .task { await model.load(environment) }
        .sheet(item: $report) { CoverReportView(seed: $0) }
    }

    private func quick(_ card: CoverVenueCard) {
        guard environment.canSubmitReports else { environment.globalNotice = "Reporting will be available after IlliniCover connects."; return }
        guard let cents = card.cover?.price.scalarCents,
              cents == CoverPrice.normalizedReportCents(cents) else {
            report = .init(venue: card.venue, decision: card.cover, interaction: .confirm)
            return
        }
        Task { show((await model.quickReport(card, environment: environment)).coverNotice) }
    }

    private func show(_ value: String) {
        Haptics.success(); notice = value
        Task { try? await Task.sleep(for: .seconds(2)); notice = nil }
    }
}

private struct BarRow: View {
    let card: CoverVenueCard
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    Text(card.venue.name).font(.headline)
                    Spacer()
                    Text(card.cover?.price.displayText ?? "—").font(.title2.bold()).monospacedDigit()
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(card.venue.name).font(.headline)
                    Text(card.cover?.price.displayText ?? "—").font(.title2.bold()).monospacedDigit()
                }
            }
            Text(card.cover?.presentationSourceLabel ?? "No current estimate").foregroundStyle(.secondary)
            if let evidence = card.cover?.evidenceText { Text(evidence).font(.caption).foregroundStyle(.secondary) }
            if !card.vibes.tags.isEmpty { Text(card.vibes.tags.joined(separator: " · ")).font(.caption) }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
        .accessibilityLabel([
            card.venue.name,
            card.cover?.price.spokenText ?? "cover unavailable",
            card.cover?.presentationSourceLabel,
            card.cover?.evidenceText,
            card.vibes.tags.joined(separator: ", ").nilIfBlank,
        ].compactMap { $0 }.joined(separator: ", "))
        .accessibilityIdentifier("cover-venue")
    }
}
