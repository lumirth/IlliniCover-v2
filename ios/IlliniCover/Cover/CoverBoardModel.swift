import Foundation
import Observation

@MainActor
@Observable
final class CoverBoardModel {
    enum WrongPriceAction: Equatable {
        case adjust
        case submit(Int)
    }

    enum LoadState: Equatable {
        case idle, loading, loaded, failed(String)
    }

    var venues: [CoverVenueCard] = []
    var state: LoadState = .idle
    var isRefreshing = false
    var isOffline = false
    var cachedAt: Date?
    var serverGeneratedAt: Date?
    var submittingVenueIDs: Set<String> = []

    private var didLoad = false
    private static let cacheKey = "cover-board-v2"

    static func wrongPriceAction(for decision: CoverDecision, selectedCents: Int) -> WrongPriceAction {
        guard let displayedCents = decision.price.scalarCents else { return .submit(selectedCents) }
        return CoverPrice.normalizedReportCents(displayedCents) == selectedCents ? .adjust : .submit(selectedCents)
    }

    func sortedVenues(by sort: VenueSort) -> [CoverVenueCard] {
        venues.sorted { left, right in
            let ordered: ComparisonResult
            switch sort {
            case .openDate:
                ordered = compareOptional(left.venue.openedYear, right.venue.openedYear)
            case .name:
                ordered = .orderedSame
            case .lowestReports:
                ordered = compareOptional(reportPriceFloor(left.cover.price), reportPriceFloor(right.cover.price))
            case .recentlyUpdated:
                ordered = compareNewestFirst(left.latestActivityAt, right.latestActivityAt)
            }
            if ordered == .orderedSame {
                return left.venue.name.localizedCaseInsensitiveCompare(right.venue.name) == .orderedAscending
            }
            return ordered == .orderedAscending
        }
    }

    func load(environment: AppEnvironment) async {
        guard !didLoad else { return }
        didLoad = true
        state = .loading

        if let cached = try? await environment.database.cached(CoverBoardResponse.self, key: Self.cacheKey) {
            venues = cached.0.venues
            cachedAt = cached.1.fetchedAt
            serverGeneratedAt = cached.1.serverGeneratedAt ?? cached.0.generatedAt
            state = .loaded
        }
        await refresh(environment: environment)
    }

    func refresh(environment: AppEnvironment) async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        let cached = try? await environment.database.cached(CoverBoardResponse.self, key: Self.cacheKey)
        do {
            let result = try await environment.api.coverBoard(eTag: cached?.1.etag)
            if let board = result.value {
                let fetchedAt = Date.now
                venues = board.venues
                cachedAt = fetchedAt
                serverGeneratedAt = board.generatedAt
                try await environment.database.cache(
                    board,
                    key: Self.cacheKey,
                    etag: result.eTag,
                    fetchedAt: fetchedAt,
                    serverGeneratedAt: board.generatedAt
                )
            } else if result.notModified {
                let fetchedAt = Date.now
                cachedAt = fetchedAt
                serverGeneratedAt = cached?.1.serverGeneratedAt ?? cached?.0.generatedAt
                try await environment.database.touchCache(
                    key: Self.cacheKey,
                    fetchedAt: fetchedAt,
                    etag: result.eTag
                )
            }
            isOffline = false
            state = .loaded
            await environment.outbox.drain()
        } catch {
            isOffline = !venues.isEmpty
            state = venues.isEmpty ? .failed(error.localizedDescription) : .loaded
        }
    }

    func displayCard(_ card: CoverVenueCard, at now: Date) -> CoverVenueCard {
        guard let cachedAt, let serverGeneratedAt else { return card }
        return CoverVenueCard(
            venue: card.venue,
            cover: card.cover.displaying(
                at: now,
                serverGeneratedAt: serverGeneratedAt,
                fetchedAt: cachedAt
            ),
            recentReportCount: card.recentReportCount,
            latestActivityAt: card.latestActivityAt,
            vibes: card.vibes
        )
    }

    func quickSubmit(
        venue: Venue,
        decision: CoverDecision,
        cents: Int,
        interaction: CoverInteraction,
        environment: AppEnvironment
    ) async -> SubmissionOutcome {
        guard environment.canSubmitReports else {
            environment.globalNotice = AppEnvironment.accountLinkConflictNotice
            return .failed
        }
        guard !submittingVenueIDs.contains(venue.id) else { return .failed }
        submittingVenueIDs.insert(venue.id)
        defer { submittingVenueIDs.remove(venue.id) }
        let id = UUID().uuidString
        let request = CoverSubmissionRequest(
            submissionId: id,
            venueId: venue.id,
            observedAt: .now,
            vantagePoint: .unknown,
            location: environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil,
            cover: CoverObservationRequest(
                priceCents: CoverPrice.normalizedReportCents(cents),
                interaction: interaction,
                displayedDecisionId: decision.decisionId,
                // A displayed scalar was present before this quick action. The
                // reporter may choose a different quick value, but that does
                // not retroactively make the original UI un-prefilled.
                pricePrefilled: decision.price.scalarCents != nil,
                priceTouched: interaction != .quickConfirm
            ),
            vibes: [],
            entryPoint: interaction == .quickConfirm ? "bar_card_quick_confirm" : "bar_card_quick_price"
        )
        do {
            _ = try await environment.api.submitCover(request)
            await refresh(environment: environment)
            return .sent
        } catch let error as APIClientError where error.isRetryableSubmissionFailure || error.isUnauthorized {
            do {
                try await environment.outbox.enqueue(id: id, kind: .cover, observedAt: request.observedAt, value: request)
                isOffline = true
                return .queued
            } catch { return .failed }
        } catch { return .failed }
    }

    private func reportPriceFloor(_ price: CoverPrice) -> Int? {
        switch price {
        case .single(let cents): cents
        case .range(let low, _): low
        case .unavailable: nil
        }
    }

    private func compareOptional<T: Comparable>(_ left: T?, _ right: T?) -> ComparisonResult {
        switch (left, right) {
        case let (left?, right?): left < right ? .orderedAscending : (left > right ? .orderedDescending : .orderedSame)
        case (nil, nil): .orderedSame
        case (nil, _?): .orderedDescending
        case (_?, nil): .orderedAscending
        }
    }

    private func compareNewestFirst<T: Comparable>(_ left: T?, _ right: T?) -> ComparisonResult {
        switch (left, right) {
        case let (left?, right?): left > right ? .orderedAscending : (left < right ? .orderedDescending : .orderedSame)
        case (nil, nil): .orderedSame
        case (nil, _?): .orderedDescending
        case (_?, nil): .orderedAscending
        }
    }
}
