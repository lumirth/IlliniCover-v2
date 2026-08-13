import SwiftUI

struct CoverBoardView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @State private var model = CoverBoardModel()
    @State private var notice: String?
    @State private var sharePayload: BoardSharePayload?
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.displayScale) private var displayScale

    private var sortedVenues: [CoverVenueCard] {
        model.sortedVenues(by: environment.settings.sort)
    }

    var body: some View {
        Group {
            switch model.state {
            case .idle where model.venues.isEmpty,
                 .loading where model.venues.isEmpty:
                ProgressView("Loading cover…")
            case .failed(let message) where model.venues.isEmpty:
                ContentUnavailableView("Cover unavailable", systemImage: "wifi.exclamationmark", description: Text(message))
                    .overlay(alignment: .bottom) {
                        Button("Retry") { Task { await model.refresh(environment: environment) } }
                            .buttonStyle(.borderedProminent)
                            .padding()
                    }
            default:
                board
            }
        }
        .navigationTitle("Bars")
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Menu {
                    Picker("Sort bars", selection: Bindable(environment.settings).sort) {
                        ForEach(VenueSort.allCases) { Text($0.rawValue).tag($0) }
                    }
                } label: {
                    Label("Sort bars", systemImage: "arrow.up.arrow.down")
                }

                Button {
                    Haptics.selection()
                    sharePayload = makeSharePayload()
                } label: {
                    Label("Share bars", systemImage: "square.and.arrow.up")
                }
                .disabled(sortedVenues.isEmpty)
            }
        }
        .overlay(alignment: .top) {
            if let notice {
                Text(notice)
                    .font(.subheadline.weight(.semibold))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 9)
                    .background(.regularMaterial, in: .capsule)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .padding(.top, 8)
            }
        }
        .task { await model.load(environment: environment) }
        .sheet(item: $sharePayload) { payload in
            BoardShareActivityView(payload: payload)
                .presentationDetents([.medium, .large])
        }
    }

    private var board: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if model.isOffline {
                    OfflineBanner(text: "Showing cached cover. Report freshness continues to age while offline.")
                }
                ForEach(sortedVenues) { card in
                    TimelineView(.periodic(from: .now, by: 60)) { timeline in
                        let displayedCard = model.displayCard(card, at: timeline.date)
                        BarCardView(
                            card: displayedCard,
                            isSubmitting: model.submittingVenueIDs.contains(card.venue.id),
                            open: { router.push(.venue(card.venue.id)) },
                            reportRight: { openConfirm(displayedCard) },
                            quickConfirm: { quickConfirm(displayedCard) },
                            reportWrong: { openWrong(displayedCard) },
                            quickPrice: { cents in
                                switch CoverBoardModel.wrongPriceAction(for: displayedCard.cover, selectedCents: cents) {
                                case .adjust:
                                    openWrong(displayedCard)
                                case .submit(let selectedCents):
                                    quickSubmit(displayedCard, cents: selectedCents, interaction: .direct)
                                }
                            }
                        )
                    }
                }
                if let cachedAt = model.cachedAt {
                    Text("Updated \(cachedAt.formatted(.relative(presentation: .named)))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 8)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
        .background(ICTheme.background)
        .refreshable { await model.refresh(environment: environment) }
    }

    private func openConfirm(_ card: CoverVenueCard) {
        guard reportingIsAvailable() else { return }
        router.sheet = .coverReport(CoverReportSeed(
            venue: card.venue,
            decision: card.cover,
            interaction: .confirm,
            initialPriceCents: card.cover.price.scalarCents
        ))
    }

    private func quickConfirm(_ card: CoverVenueCard) {
        guard reportingIsAvailable() else { return }
        guard let cents = card.cover.price.scalarCents else {
            openConfirm(card)
            return
        }
        quickSubmit(card, cents: cents, interaction: .quickConfirm)
    }

    private func openWrong(_ card: CoverVenueCard) {
        guard reportingIsAvailable() else { return }
        router.sheet = .coverReport(CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: card.cover.price.scalarCents))
    }

    private func quickSubmit(_ card: CoverVenueCard, cents: Int, interaction: CoverInteraction) {
        guard reportingIsAvailable() else { return }
        Task {
            let outcome = await model.quickSubmit(venue: card.venue, decision: card.cover, cents: cents, interaction: interaction, environment: environment)
            switch outcome {
            case .sent:
                showNotice(outcome.coverNotice, haptic: .success)
            case .queued:
                showNotice(outcome.coverNotice, haptic: .selection)
            case .failed:
                showNotice(outcome.coverNotice, haptic: .warning)
            }
        }
    }

    private func reportingIsAvailable() -> Bool {
        guard environment.canSubmitReports else {
            environment.globalNotice = AppEnvironment.accountLinkConflictNotice
            showNotice("Reporting paused. Open Account to resolve this installation link.", haptic: .warning)
            return false
        }
        return true
    }

    private func makeSharePayload() -> BoardSharePayload {
        let cards = sortedVenues.map { model.displayCard($0, at: .now) }
        let snapshot = BoardShareSnapshot(cards: cards, generatedAt: model.serverGeneratedAt)
            .environment(\.colorScheme, colorScheme)
            .frame(width: 390)
        let renderer = ImageRenderer(content: snapshot)
        renderer.scale = displayScale
        renderer.isOpaque = true
        return BoardSharePayload(image: renderer.uiImage)
    }

    private enum NoticeHaptic { case success, selection, warning }

    private func showNotice(_ text: String, haptic: NoticeHaptic) {
        switch haptic {
        case .success: Haptics.success()
        case .selection: Haptics.selection()
        case .warning: Haptics.warning()
        }
        withAnimation(.snappy) { notice = text }
        Task {
            try? await Task.sleep(for: .seconds(2))
            withAnimation(.easeOut) { notice = nil }
        }
    }
}

private struct BarCardView: View {
    let card: CoverVenueCard
    let isSubmitting: Bool
    let open: () -> Void
    let reportRight: () -> Void
    let quickConfirm: () -> Void
    let reportWrong: () -> Void
    let quickPrice: (Int) -> Void

    private var presentedCover: CoverDecision { card.cover }

    private var sourceColor: Color {
        if presentedCover.isAdvertisedConflict { return Color.orange }
        switch presentedCover.source {
        case .historical: return ICTheme.estimate
        case .unusual, .unconfirmed: return Color.orange
        case .unavailable: return Color.secondary
        default: return ICTheme.accent
        }
    }

    private var statusSystemImage: String {
        if presentedCover.isAdvertisedConflict { return "megaphone.fill" }
        switch presentedCover.source {
        case .live: return "checkmark"
        case .advertised, .historical: return "sparkles"
        case .mixed: return "arrow.left.arrow.right"
        case .unconfirmed, .unusual: return "ellipsis"
        case .unavailable: return "info.circle"
        }
    }

    var body: some View {
        ZStack {
            Button(action: open) {
                Rectangle()
                    .fill(.clear)
                    .contentShape(.rect)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("bar-card-\(card.venue.slug)")
            .accessibilityLabel("\(card.venue.name). \(presentedCover.price.spokenText). \(presentedCover.presentationSourceLabel). \(presentedCover.evidenceText). Open details.")
            .contextMenu {
                Button("Open details", systemImage: "arrow.right.circle", action: open)
                Button("Report right price", systemImage: "checkmark", action: reportRight)
                Button("Report wrong price", systemImage: "xmark", action: reportWrong)
            }

            VStack(spacing: 0) {
                VStack(spacing: 12) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(card.venue.name)
                            .font(.system(size: 26, weight: .bold))
                        Spacer(minLength: 12)
                        Text(presentedCover.price.displayText)
                            .font(.system(size: 26, weight: .bold))
                            .foregroundStyle(presentedCover.source == .historical ? ICTheme.estimate : .primary)
                            .monospacedDigit()
                            .minimumScaleFactor(0.72)
                    }
                    HStack(alignment: .firstTextBaseline) {
                        Text(presentedCover.evidenceText)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                        Spacer(minLength: 8)
                        Label(presentedCover.presentationSourceLabel, systemImage: statusSystemImage)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(sourceColor)
                            .lineLimit(1)
                    }
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)

                HStack(spacing: 8) {
                    Button(action: reportRight) {
                        Label(isSubmitting ? "Sending" : "Right", systemImage: isSubmitting ? "arrow.triangle.2.circlepath" : "checkmark")
                    }
                    .buttonStyle(ActionPillStyle(color: ICTheme.right))
                    .disabled(isSubmitting)
                    .contextMenu {
                        Button("Quick confirm", systemImage: "checkmark.circle", action: quickConfirm)
                            .disabled(card.cover.price.scalarCents == nil)
                    }
                    .accessibilityLabel("Confirm \(presentedCover.price.spokenText) at \(card.venue.name)")

                    Button(action: reportWrong) {
                        Label("Wrong", systemImage: "xmark")
                    }
                    .buttonStyle(ActionPillStyle(color: ICTheme.wrong))
                    .disabled(isSubmitting)
                    .contextMenu {
                        ForEach([0, 500, 1_000, 2_000], id: \.self) { cents in
                            Button("Quick report \(CoverPrice.currency(cents))") { quickPrice(cents) }
                        }
                    }
                    .accessibilityLabel("Report a different cover price at \(card.venue.name)")

                    Spacer(minLength: 4)
                    StatusPill(text: presentedCover.sourcePill, color: sourceColor)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                .padding(.top, 4)
            }
        }
        .padding(16)
        .background(ICTheme.card, in: .rect(cornerRadius: 22, style: .continuous))
    }
}

#Preview("Cover board") {
    let config = AppConfiguration(apiBaseURL: URL(string: "https://example.test")!, revenueCatAPIKey: nil)
    let database = try! AppDatabase.temporary()
    let credentials = CredentialStore(service: "preview")
    NavigationStack { CoverBoardView() }
        .environment(AppEnvironment(api: PreviewAPIClient(canonicalFixtureClient: CanonicalFixtureSupport.makeClient()), database: database, credentials: credentials, settings: AppSettings(defaults: UserDefaults(suiteName: UUID().uuidString)!), configuration: config))
        .environment(AppRouter())
}
