import SwiftUI

struct VenueDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    let venueID: String
    @State private var detail: VenueCoverResponse?
    @State private var error: String?
    @State private var report: CoverReportSeed?

    var body: some View {
        Group {
            if let detail {
                List {
                    Section("Venue") {
                        if !detail.venue.address.isEmpty { Text(detail.venue.address) }
                        if let year = detail.venue.openedYear { LabeledContent("Opened", value: year.formatted(.number.grouping(.never))) }
                    }
                    Section {
                        HStack { Text("Cover").font(.headline); Spacer(); Text(detail.cover?.price.displayText ?? "—").font(.title.bold()) }
                        Text(detail.cover?.presentationSourceLabel ?? "No current estimate").foregroundStyle(.secondary)
                        if !detail.vibes.tags.isEmpty { Text(detail.vibes.tags.joined(separator: " · ")) }
                        Button("Report what you see", systemImage: "plus.bubble") {
                            report = .init(venue: detail.venue, decision: detail.cover, interaction: .direct)
                        }
                    }
                    Section("Recent reports") {
                        ForEach(detail.recentReports.prefix(5)) { report in
                            VStack(alignment: .leading) {
                                HStack { Text(report.priceText).bold(); Spacer(); Text(report.observedAt.formatted(.relative(presentation: .named))).foregroundStyle(.secondary) }
                                if !report.vibes.isEmpty { Text(report.vibes.joined(separator: " · ")).font(.caption) }
                            }
                        }
                        NavigationLink("View history") { CoverHistoryView(venueID: venueID) }
                    }
                    if !detail.deals.isEmpty {
                        Section("Tonight’s deals") { ForEach(detail.deals, id: \.id) { deal in HStack { Text(deal.displayName); Spacer(); Text(deal.priceText).bold() } } }
                    }
                    Section("Planning") { NavigationLink("Time Machine") { TimeMachineView(venue: detail.venue) } }
                    Section { ShareLink(item: DeepLink.venueURL(venueID), subject: Text(detail.venue.name), message: Text("See \(detail.venue.name) on IlliniCover")) }
                }
                .navigationTitle(detail.venue.name)
            } else if let error {
                ContentUnavailableView("Venue unavailable", systemImage: "wifi.exclamationmark", description: Text(error))
            } else { ProgressView("Loading venue…") }
        }
        .task { await load() }
        .sheet(item: $report) { CoverReportView(seed: $0) }
    }

    private func load() async {
        do { detail = try await environment.api.venueCover(venueID) }
        catch { self.error = error.localizedDescription }
    }
}

struct CoverHistoryView: View {
    @Environment(AppEnvironment.self) private var environment
    let venueID: String
    @State private var response: CoverHistoryResponse?
    @State private var error: String?

    var body: some View {
        Group {
            if let response {
                List {
                    Section {
                        Text(response.accessTier.title)
                        if response.hasMore {
                            Text(response.accessTier == .limited ? "More reports are available with Blue." : "Showing the most recent reports in the extended window.").foregroundStyle(.secondary)
                        }
                    }
                    ForEach(response.reports) { report in
                        VStack(alignment: .leading) { HStack { Text(report.priceText).bold(); Spacer(); Text(report.observedAt.formatted(date: .abbreviated, time: .shortened)) }; Text(report.vibes.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary) }
                    }
                }.navigationTitle("Cover history")
            } else if let error { ContentUnavailableView("History unavailable", systemImage: "clock.badge.exclamationmark", description: Text(error)) }
            else { ProgressView() }
        }
        .task { do { response = try await environment.api.coverHistory(venueID) } catch { self.error = error.localizedDescription } }
    }
}
