import Observation
import SwiftUI

@MainActor
@Observable
final class DealsModel {
    var venues: [VenueDeals] = []
    var serviceDate = "Tonight"
    var isLoading = true
    var isRefreshing = false
    var isOffline = false
    var errorMessage: String?
    var submittingDealIDs: Set<String> = []
    private var didLoad = false
    private static let cacheKey = "deals-v2"

    func isCurrentServiceNight(at date: Date = .now) -> Bool {
        serviceDate == ServiceNight.serviceDate(containing: date)
    }

    func sortedVenues(by sort: DealsSort) -> [VenueDeals] {
        venues.sorted { left, right in
            if left.deals.isEmpty != right.deals.isEmpty { return !left.deals.isEmpty }
            if left.deals.isEmpty { return compareNames(left, right) }
            let ordered: ComparisonResult
            switch sort {
            case .openDate:
                ordered = compareOptional(left.venue.openedYear, right.venue.openedYear)
            case .name:
                ordered = .orderedSame
            case .lowestReports:
                ordered = compareOptional(averageSinglePrice(left), averageSinglePrice(right))
            case .recentlyUpdated:
                ordered = compareOptionalDateDescending(mostRecentActivity(left), mostRecentActivity(right))
            }
            return ordered == .orderedSame ? compareNames(left, right) : ordered == .orderedAscending
        }
    }

    func load(environment: AppEnvironment) async {
        guard !didLoad else { return }
        didLoad = true
        if let cached = try? await environment.database.cached(DealsResponse.self, key: Self.cacheKey) {
            apply(cached.0)
            isLoading = false
        }
        await refresh(environment: environment)
    }

    func refresh(environment: AppEnvironment) async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false; isLoading = false }
        let cached = try? await environment.database.cached(DealsResponse.self, key: Self.cacheKey)
        do {
            let response = try await environment.api.deals(eTag: cached?.1.etag)
            if let deals = response.value {
                apply(deals)
                try await environment.database.cache(deals, key: Self.cacheKey, etag: response.eTag, serverGeneratedAt: deals.generatedAt)
            }
            isOffline = false
            errorMessage = nil
        } catch {
            isOffline = !venues.isEmpty
            errorMessage = venues.isEmpty ? error.localizedDescription : nil
        }
    }

    func submit(
        venue: Venue,
        deal: Deal,
        action: DealEvidenceAction,
        environment: AppEnvironment
    ) async -> SubmissionOutcome {
        let observedAt = Date.now
        guard environment.canSubmitReports else {
            environment.globalNotice = AppEnvironment.accountLinkConflictNotice
            return .failed
        }
        guard isCurrentServiceNight(at: observedAt), !submittingDealIDs.contains(deal.id) else { return .failed }
        submittingDealIDs.insert(deal.id)
        defer { submittingDealIDs.remove(deal.id) }
        let request = DealEvidenceRequest(
            submissionId: UUID().uuidString,
            venueId: venue.id,
            observedAt: observedAt,
            action: action,
            targetDealId: deal.id,
            targetPredictionId: deal.predictionId,
            submittedDeal: nil,
            serviceDateLocal: serviceDate,
            targetLocalDateTime: nil
        )
        do {
            _ = try await environment.api.submitDeal(request)
            await refresh(environment: environment)
            return .sent
        } catch let error as APIClientError where error.isRetryableSubmissionFailure || error.isUnauthorized {
            do {
                try await environment.outbox.enqueue(id: request.submissionId, kind: .deal, observedAt: request.observedAt, value: request)
                isOffline = true
                return .queued
            } catch { return .failed }
        } catch { return .failed }
    }

    private func apply(_ response: DealsResponse) {
        venues = response.venues
        serviceDate = response.serviceDate
    }

    private func compareNames(_ left: VenueDeals, _ right: VenueDeals) -> Bool {
        left.venue.name.localizedCaseInsensitiveCompare(right.venue.name) == .orderedAscending
    }

    private func averageSinglePrice(_ venue: VenueDeals) -> Double? {
        let prices = venue.deals.compactMap { deal -> Int? in
            if case .single(let cents) = deal.price { return cents }
            return nil
        }
        guard !prices.isEmpty else { return nil }
        return Double(prices.reduce(0, +)) / Double(prices.count)
    }

    private func mostRecentActivity(_ venue: VenueDeals) -> Date? {
        venue.deals.compactMap(\.latestActivityAt).max()
    }

    private func compareOptional<T: Comparable>(_ left: T?, _ right: T?) -> ComparisonResult {
        switch (left, right) {
        case let (left?, right?): left < right ? .orderedAscending : (left > right ? .orderedDescending : .orderedSame)
        case (nil, nil): .orderedSame
        case (nil, _?): .orderedDescending
        case (_?, nil): .orderedAscending
        }
    }

    private func compareOptionalDateDescending(_ left: Date?, _ right: Date?) -> ComparisonResult {
        switch (left, right) {
        case let (left?, right?): left > right ? .orderedAscending : (left < right ? .orderedDescending : .orderedSame)
        case (nil, nil): .orderedSame
        case (nil, _?): .orderedDescending
        case (_?, nil): .orderedAscending
        }
    }
}

struct DealsView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @State private var model = DealsModel()
    @State private var confirmation: DealConfirmation?
    @State private var notice: String?

    private struct DealConfirmation: Identifiable {
        enum Kind { case confirm, deny }
        let id = UUID()
        let venue: Venue
        let deal: Deal
        let kind: Kind
    }

    private var sortedVenues: [VenueDeals] {
        model.sortedVenues(by: environment.settings.dealsSort)
    }

    var body: some View {
        Group {
            if model.isLoading && model.venues.isEmpty {
                ProgressView("Loading tonight’s deals…")
            } else if let error = model.errorMessage, model.venues.isEmpty {
                VStack(spacing: 14) {
                    ContentUnavailableView("Deals unavailable", systemImage: "tag.slash", description: Text(error))
                    Button("Retry") { Task { await model.refresh(environment: environment) } }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("deals-retry")
                }
            } else {
                dealsList
            }
        }
        .navigationTitle("Deals")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Picker("Sort deals", selection: Bindable(environment.settings).dealsSort) {
                        ForEach(DealsSort.allCases) { Text($0.rawValue).tag($0) }
                    }
                } label: {
                    Label("Sort deals", systemImage: "arrow.up.arrow.down")
                }
            }
        }
        .overlay(alignment: .top) {
            if let notice {
                Text(notice).font(.subheadline.weight(.semibold)).padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.regularMaterial, in: .capsule).padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .alert(item: $confirmation) { item in
            switch item.kind {
            case .confirm:
                Alert(
                    title: Text("Confirm Deal"),
                    message: Text("Is this deal available tonight?"),
                    primaryButton: .default(Text("Yes, Available")) { submit(item, action: .confirmPresent) },
                    secondaryButton: .cancel()
                )
            case .deny:
                Alert(
                    title: Text("Not Available?"),
                    message: Text("Report that this deal isn’t available tonight."),
                    primaryButton: .destructive(Text("Not Available")) { submit(item, action: .denyPresent) },
                    secondaryButton: .cancel()
                )
            }
        }
        .task { await model.load(environment: environment) }
    }

    private var dealsList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20, pinnedViews: .sectionHeaders) {
                if !model.isCurrentServiceNight() {
                    OfflineBanner(text: "These deals are from \(model.serviceDate). They’re read-only after the 5:00 AM Chicago service-night rollover. Pull to refresh for tonight.")
                        .accessibilityIdentifier("stale-deals-read-only")
                } else if model.isOffline {
                    OfflineBanner(text: "Showing cached deals for tonight. Pull to refresh when you’re back online.")
                } else if environment.hasAccountLinkConflict {
                    OfflineBanner(text: "Reporting is paused until this installation’s account link is resolved in Account.")
                }
                ForEach(sortedVenues) { venueDeals in
                    Section {
                        if venueDeals.deals.isEmpty {
                            Text("No deals reported for tonight yet.")
                                .font(.subheadline).foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 16).padding(.vertical, 12)
                        } else {
                            VStack(spacing: 10) {
                                ForEach(venueDeals.deals) { deal in
                                    DealRow(
                                        deal: deal,
                                        isSubmitting: model.submittingDealIDs.contains(deal.id),
                                        isActionable: model.isCurrentServiceNight() && environment.canSubmitReports,
                                        confirm: { confirmation = .init(venue: venueDeals.venue, deal: deal, kind: .confirm) },
                                        deny: { confirmation = .init(venue: venueDeals.venue, deal: deal, kind: .deny) },
                                        edit: { router.sheet = .dealComposer(.init(venue: venueDeals.venue, mode: .review, deal: deal, suggestions: venueDeals.deals, serviceDate: model.serviceDate)) }
                                    )
                                }
                            }
                            .disabled(!model.isCurrentServiceNight() || !environment.canSubmitReports)
                            .accessibilityHint(model.isCurrentServiceNight() ? "" : "Refresh the deal slate before adding a deal")
                            .padding(.horizontal, 16)
                        }
                    } header: {
                        HStack {
                            Button {
                                router.push(.venue(venueDeals.venue.id))
                            } label: {
                                HStack(spacing: 7) {
                                    Text(venueDeals.venue.name).font(.title2.bold())
                                    Text("\(venueDeals.deals.count)")
                                        .font(.caption.bold())
                                        .foregroundStyle(.secondary)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 3)
                                        .background(.secondary.opacity(0.14), in: .capsule)
                                }
                                .contentShape(.rect)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Open \(venueDeals.venue.name), \(venueDeals.deals.count) deals")
                            Spacer()
                            Button {
                                router.sheet = .dealComposer(.init(venue: venueDeals.venue, mode: .add, deal: nil, suggestions: venueDeals.deals, serviceDate: model.serviceDate))
                            } label: {
                                Image(systemName: "plus")
                                    .font(.system(size: 16, weight: .bold))
                                    .frame(width: 34, height: 34)
                                    .foregroundStyle(.white)
                                    .background(ICTheme.accent, in: .circle)
                                    .frame(minWidth: 48, minHeight: 44)
                            }
                            .accessibilityLabel("Add Deal")
                            .disabled(!model.isCurrentServiceNight() || !environment.canSubmitReports)
                            .accessibilityHint(
                                environment.hasAccountLinkConflict
                                    ? "Resolve this installation’s account link before reporting"
                                    : (model.isCurrentServiceNight() ? "" : "Refresh tonight’s deal slate first")
                            )
                        }
                        .padding(.horizontal, 16).padding(.vertical, 8)
                        .background(ICTheme.background)
                    }
                }
            }
            .padding(.bottom, 24)
        }
        .background(ICTheme.background)
        .refreshable { await model.refresh(environment: environment) }
    }

    private func submit(_ item: DealConfirmation, action: DealEvidenceAction) {
        Task {
            guard environment.canSubmitReports else {
                environment.globalNotice = AppEnvironment.accountLinkConflictNotice
                Haptics.warning()
                withAnimation(.snappy) { notice = "Reporting paused. Resolve this installation link in Account." }
                return
            }
            guard model.isCurrentServiceNight() else {
                Haptics.warning()
                withAnimation(.snappy) { notice = "Refresh tonight’s deals before reporting." }
                try? await Task.sleep(for: .seconds(2))
                withAnimation(.easeOut) { notice = nil }
                return
            }
            let outcome = await model.submit(venue: item.venue, deal: item.deal, action: action, environment: environment)
            switch outcome {
            case .sent: Haptics.success()
            case .queued: Haptics.selection()
            case .failed: Haptics.warning()
            }
            withAnimation(.snappy) {
                notice = outcome.dealNotice(for: action)
            }
            try? await Task.sleep(for: .seconds(2))
            withAnimation(.easeOut) { notice = nil }
        }
    }
}

private struct DealRow: View {
    let deal: Deal
    let isSubmitting: Bool
    let isActionable: Bool
    let confirm: () -> Void
    let deny: () -> Void
    let edit: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Button(action: edit) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 6) {
                        Text(deal.price.displayText)
                            .font(.system(size: 16, weight: .bold).monospacedDigit())
                            .fixedSize(horizontal: true, vertical: false)
                        Text(deal.name)
                            .font(.system(size: 16, weight: .semibold))
                            .lineLimit(1)
                            .truncationMode(.tail)
                        if let serving = deal.serving {
                            Text(serving)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .fixedSize(horizontal: true, vertical: false)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(ICTheme.background, in: .capsule)
                        }
                    }
                    HStack(spacing: 6) {
                        Label(
                            deal.presentationStatus.label,
                            systemImage: deal.presentationStatus.isPrediction ? "sparkles" : "checkmark.circle.fill"
                        )
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(deal.presentationStatus.isPrediction ? ICTheme.estimate : ICTheme.accent)
                        .lineLimit(1)
                        if let timing = deal.timing.displayText {
                            Text(timing)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .disabled(isSubmitting || !isActionable)
            .accessibilityLabel("Edit deal for \(deal.price.displayText) \(deal.name)")
            .accessibilityHint("Opens the deal correction form")
            .frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: 10) {
                Button(action: confirm) {
                    Image(systemName: isSubmitting ? "arrow.triangle.2.circlepath" : "checkmark")
                        .frame(width: 44, height: 44)
                        .foregroundStyle(ICTheme.right)
                        .background(ICTheme.right.opacity(0.18), in: .circle)
                }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Confirm \(deal.name)")
                Button(action: deny) {
                    Image(systemName: "xmark")
                        .frame(width: 44, height: 44)
                        .foregroundStyle(ICTheme.wrong)
                        .background(ICTheme.wrong.opacity(0.18), in: .circle)
                }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Mark \(deal.name) not present")
            }
            .disabled(isSubmitting || !isActionable)
        }
        .padding(16)
        .background(ICTheme.card, in: .rect(cornerRadius: 22, style: .continuous))
        .contextMenu {
            if isActionable {
                Button("Confirm Deal", systemImage: "checkmark", action: confirm)
                Button("Mark Not Present", systemImage: "xmark", action: deny)
                Button("Edit Deal", systemImage: "pencil", action: edit)
            } else {
                Text("Refresh for tonight’s deals")
            }
        }
        .opacity(isActionable ? 1 : 0.72)
        .accessibilityIdentifier("deal-row-\(deal.id)")
    }
}
