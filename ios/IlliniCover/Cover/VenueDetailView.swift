import SwiftUI

@MainActor
@Observable
final class VenueDetailModel {
    var detail: VenueCoverResponse?
    var isLoading = true
    var errorMessage: String?
    var fetchedAt: Date?

    func load(id: String, api: any AppAPI) async {
        isLoading = detail == nil
        defer { isLoading = false }
        do {
            detail = try await api.venueCover(id: id)
            fetchedAt = .now
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct VenueDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.displayScale) private var displayScale
    let venueID: String
    @State private var model = VenueDetailModel()
    @State private var showStatusHelp = false
    @State private var sharePayload: VenueSharePayload?

    var body: some View {
        Group {
            if let detail = model.detail {
                detailBody(detail)
            } else if model.isLoading {
                ProgressView("Loading bar…")
            } else {
                VStack(spacing: 14) {
                    ContentUnavailableView("Bar unavailable", systemImage: "building.2.crop.circle", description: Text(model.errorMessage ?? "Try again."))
                    Button("Retry") { Task { await model.load(id: venueID, api: environment.api) } }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("venue-detail-retry")
                }
            }
        }
        .navigationTitle(model.detail?.venue.name ?? "Bar")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            if let venue = model.detail?.venue {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        Haptics.selection()
                        openDirections(to: venue)
                    } label: {
                        Image(systemName: "mappin.and.ellipse")
                    }
                    .accessibilityLabel("Navigate to bar")

                    Button {
                        guard let detail = model.detail else { return }
                        Haptics.selection()
                        sharePayload = makeSharePayload(detail)
                    } label: {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("Share bar")
                }
            }
        }
        .task { await model.load(id: venueID, api: environment.api) }
        .refreshable { await model.load(id: venueID, api: environment.api) }
        .sheet(item: $sharePayload) { payload in
            VenueShareActivityView(payload: payload)
                .presentationDetents([.medium, .large])
        }
    }

    private func detailBody(_ detail: VenueCoverResponse) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    if let address = detail.venue.address {
                        Label(address, systemImage: "mappin.and.ellipse")
                    }
                    if let year = detail.venue.openedYear {
                        Text("Opened \(String(year))").padding(.leading, 28)
                    }
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)

                TimelineView(.periodic(from: .now, by: 60)) { timeline in
                    coverCard(detail, at: timeline.date)
                }

                Button("Contribute") {
                    router.sheet = .coverReport(CoverReportSeed(
                        venue: detail.venue,
                        decision: displayDecision(detail.cover, at: .now),
                        interaction: .direct,
                        initialPriceCents: detail.cover.price.scalarCents
                    ))
                }
                .buttonStyle(PrimaryActionStyle())
                .disabled(!environment.canSubmitReports)
                .accessibilityHint("Report cover, line, or crowd conditions")

                VStack(alignment: .leading, spacing: 10) {
                    Text("Recent Reports")
                        .font(.title2.bold())
                        .padding(.horizontal, 8)
                    VStack(spacing: 0) {
                        ForEach(Array(detail.recentReports.prefix(4).enumerated()), id: \.element.id) { index, report in
                            RecentReportRow(report: report)
                            if index < min(detail.recentReports.count, 4) - 1 { Divider().padding(.leading, 14) }
                        }
                        if detail.recentReports.isEmpty {
                            Text("No reports this service night.")
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14)
                        }
                        Divider().padding(.leading, 14)
                        Button {
                            router.push(.coverHistory(detail.venue.id))
                        } label: {
                            HStack {
                                Text("More Reports")
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.tertiary)
                            }
                            .frame(minHeight: 44)
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(ICTheme.accent)
                        .padding(.horizontal, 14)
                        .accessibilityIdentifier("open-cover-history")
                        .accessibilityHint("Opens limited or extended report history, including older service nights")
                    }
                    .background(ICTheme.card, in: .rect(cornerRadius: 22, style: .continuous))
                }

                Button {
                    router.push(.timeMachine(detail.venue.id))
                } label: {
                    Label("Open Time Machine", systemImage: "clock.arrow.circlepath")
                        .frame(maxWidth: .infinity, minHeight: 48)
                }
                .buttonStyle(.bordered)

                if !detail.deals.isEmpty {
                    Text("Tonight’s deals").font(.title2.bold())
                    VStack(spacing: 10) {
                        ForEach(detail.deals) { deal in CompactDealRow(deal: deal) }
                    }
                }

                if let decisionID = detail.cover.decisionId {
                    Text("Decision \(decisionID)")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.tertiary)
                        .textSelection(.enabled)
                }
            }
            .padding(16)
        }
        .background(ICTheme.background)
    }

    private func coverCard(_ detail: VenueCoverResponse, at now: Date) -> some View {
        let decision = displayDecision(detail.cover, at: now)
        return VStack(spacing: 0) {
            HStack {
                Text("COVER")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    Haptics.selection()
                    showStatusHelp = true
                } label: {
                    Label(detailStatusLabel(decision), systemImage: statusIcon(decision.source))
                        .font(.subheadline.weight(.semibold))
                }
                .buttonStyle(.plain)
                .foregroundStyle(decision.source == .historical ? ICTheme.estimate : ICTheme.accent)
                .popover(isPresented: $showStatusHelp) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(decision.presentationSourceLabel).font(.headline)
                        Text(statusExplanation(decision))
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                    .presentationCompactAdaptation(.popover)
                }
            }
            .padding(.bottom, 16)

            Text(decision.price.displayText)
                .font(.system(size: 64, weight: .bold, design: .rounded))
                .minimumScaleFactor(0.6)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .center)

            HStack(alignment: .bottom, spacing: 12) {
                Text(decision.evidenceText)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if decision.source == .historical, decision.price != .unavailable {
                    Button {
                        router.push(.estimate(detail.venue.id))
                    } label: {
                        HStack(spacing: 6) {
                            Text("Why \(decision.price.displayText)?")
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                        }
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(ICTheme.accent)
                    .font(.subheadline.weight(.semibold))
                    .fixedSize()
                    .accessibilityHint("Opens the estimate explanation")
                }
            }
            .padding(.top, 20)

            if !detail.vibes.tags.isEmpty {
                ScrollView(.horizontal) {
                    HStack { ForEach(detail.vibes.tags, id: \.self) { StatusPill(text: $0, color: .secondary) } }
                }
                .scrollIndicators(.hidden)
                .padding(.top, 14)
            }
        }
        .padding(20)
        .background(ICTheme.card, in: .rect(cornerRadius: 24, style: .continuous))
    }

    private func displayDecision(_ decision: CoverDecision, at now: Date) -> CoverDecision {
        guard let fetchedAt = model.fetchedAt else { return decision }
        return decision.displaying(at: now, serverGeneratedAt: fetchedAt, fetchedAt: fetchedAt)
    }

    private func statusExplanation(_ decision: CoverDecision) -> String {
        if decision.isAdvertisedConflict {
            return "The venue has advertised more than one current price. No community report has resolved the conflict yet."
        }
        switch decision.source {
        case .live: return "Recent admitted community reports determine this cover."
        case .advertised: return "The venue directly advertised this cover for the current service night."
        case .historical: return "This is an estimate based on past reports around this time, adjusted by any useful same-night context."
        case .mixed: return "More than one current price remains plausible. Recent reports show the evidence."
        case .unconfirmed, .unusual: return "Current evidence exists, but IlliniCover has a reason to present it cautiously."
        case .unavailable: return "IlliniCover does not have enough useful evidence for an answer yet."
        }
    }

    private func detailStatusLabel(_ decision: CoverDecision) -> String {
        if decision.isAdvertisedConflict { return "Advertised conflict" }
        switch decision.source {
        case .historical: return "Estimate"
        case .advertised: return "Advertised"
        case .mixed: return "Mixed"
        default: return decision.source.label
        }
    }

    private func statusIcon(_ source: CoverSource) -> String {
        switch source {
        case .live: "checkmark.circle.fill"
        case .advertised: "megaphone.fill"
        case .historical: "sparkles"
        case .mixed: "point.3.connected.trianglepath.dotted"
        case .unconfirmed, .unusual: "exclamationmark.triangle.fill"
        case .unavailable: "questionmark.circle.fill"
        }
    }

    private func makeSharePayload(_ detail: VenueCoverResponse) -> VenueSharePayload {
        let descriptor = VenueShareDescriptor(venue: detail.venue)
        let snapshot = VenueShareSnapshot(detail: detail)
            .environment(\.colorScheme, colorScheme)
            .frame(width: 390)
        let renderer = ImageRenderer(content: snapshot)
        renderer.scale = displayScale
        renderer.isOpaque = true
        return VenueSharePayload(descriptor: descriptor, image: renderer.uiImage)
    }

    private func openDirections(to venue: Venue) {
        let destination = venue.address.map { "\($0), Champaign-Urbana, IL" }
            ?? "\(venue.name), Champaign-Urbana, IL"
        var components = URLComponents(string: "https://maps.apple.com/")
        components?.queryItems = [
            URLQueryItem(name: "daddr", value: destination),
            URLQueryItem(name: "dirflg", value: "w"),
        ]
        guard let url = components?.url else { return }
        Task {
            if !(await UIApplication.shared.open(url)) {
                environment.globalNotice = "Maps could not open directions to \(venue.name)."
            }
        }
    }
}

struct RecentReportRow: View {
    let report: RecentCoverReport

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(report.price?.displayText ?? "Vibe")
                .font(.headline.monospacedDigit())
                .frame(width: 68, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) {
                Text(report.observedAt.formatted(.relative(presentation: .named)))
                    .font(.subheadline)
                let details = ([report.sourceLabel, report.locationContext] + report.displayVibes.map(Optional.some)).compactMap { $0 }
                if !details.isEmpty {
                    Text(details.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(14)
    }
}

struct CompactDealRow: View {
    let deal: Deal
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(deal.price.displayText).font(.headline.monospacedDigit()).frame(width: 66, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) {
                Text(deal.name).font(.headline)
                let details = [deal.serving, deal.timing.displayText].compactMap { $0 }
                if !details.isEmpty { Text(details.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
        }
        .padding(14)
        .background(ICTheme.card, in: .rect(cornerRadius: 15, style: .continuous))
    }
}

@MainActor
@Observable
private final class CoverHistoryModel {
    var response: CoverHistoryResponse?
    var error: String?
    func load(venueID: String, api: any AppAPI) async {
        do { response = try await api.coverHistory(venueID: venueID); error = nil }
        catch { self.error = error.localizedDescription }
    }
}

struct CoverHistoryView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    let venueID: String
    @State private var model = CoverHistoryModel()

    var body: some View {
        List {
            if let error = model.error, model.response == nil {
                ContentUnavailableView {
                    Label("History unavailable", systemImage: "clock.badge.exclamationmark")
                } description: {
                    Text(error)
                } actions: {
                    Button("Retry") { Task { await model.load(venueID: venueID, api: environment.api) } }
                }
            }
            if let response = model.response {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Label(
                            response.accessTier.title,
                            systemImage: response.accessTier == .extended ? "crown.fill" : "clock"
                        )
                        .font(.headline)
                        Text("Showing reports since \(response.windowStart.formatted(date: .abbreviated, time: .omitted)).")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if response.hasMore {
                            Text("More reports exist in this history window than can be shown here.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        if response.accessTier == .limited, !environment.premium {
                            Button("View Extended History") { router.push(.premium) }
                                .font(.subheadline.weight(.semibold))
                        }
                    }
                    .padding(.vertical, 6)
                }
                ForEach(response.reports) {
                    RecentReportRow(report: $0)
                        .listRowInsets(.init())
                        .listRowBackground(Color.clear)
                }
            }
        }
        .listStyle(.plain)
        .navigationTitle("Recent Reports")
        .task { await model.load(venueID: venueID, api: environment.api) }
    }
}
