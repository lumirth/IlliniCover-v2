import Foundation

actor PreviewAPIClient: AppAPI {
    typealias AsyncBehavior = @Sendable () async throws -> Void
    typealias TokenBehavior = @Sendable (String, String, String?) async throws -> Void
    typealias DeletionStatusBehavior = @Sendable (String) async throws -> Bool
    typealias AccountBehavior = @Sendable () async throws -> AccountSummary
    typealias OutboxBehavior = @Sendable (OutboxKind, Data) async throws -> Void
    typealias CoverSubmissionBehavior = @Sendable (CoverSubmissionRequest) async throws -> Void
    typealias DealSubmissionBehavior = @Sendable (DealEvidenceRequest) async throws -> Void
    typealias DealSuggestionsBehavior = @Sendable (String, String?) async throws -> [DealSuggestion]
    typealias DealsBehavior = @Sendable (String?) async throws -> HTTPResult<DealsResponse>
    typealias VenueCoverBehavior = @Sendable (String) async throws -> VenueCoverResponse
    typealias HandbookPageBehavior = @Sendable (String) async throws -> HandbookPage

    private var account: AccountSummary?
    private var premium = false
    private(set) var rotationCount = 0
    private(set) var installationCount = 0
    private(set) var installationReadCount = 0
    private(set) var linkCount = 0
    private(set) var deletionCount = 0
    private(set) var resendCount = 0
    private(set) var outboxCount = 0
    private(set) var accountReadCount = 0
    private let createInstallationBehavior: AsyncBehavior
    private let currentInstallationBehavior: AsyncBehavior
    private let rotateInstallationBehavior: AsyncBehavior
    private let tokenOperationBehavior: TokenBehavior?
    private let linkInstallationBehavior: AsyncBehavior
    private let deleteAccountBehavior: AsyncBehavior
    private let deletionStatusBehavior: DeletionStatusBehavior
    private let accountBehavior: AccountBehavior?
    private let outboxBehavior: OutboxBehavior
    private let coverSubmissionBehavior: CoverSubmissionBehavior
    private let dealSubmissionBehavior: DealSubmissionBehavior
    private let dealSuggestionsBehavior: DealSuggestionsBehavior?
    private let dealsBehavior: DealsBehavior?
    private let venueCoverBehavior: VenueCoverBehavior?
    private let handbookPageBehavior: HandbookPageBehavior?
    private let canonicalFixtureClient: LiveAPIClient?
    private let premiumAfterAuthentication: Bool
    private var completedDeletionRequests = Set<String>()

    init(
        createInstallationBehavior: @escaping AsyncBehavior = {},
        currentInstallationBehavior: @escaping AsyncBehavior = {},
        rotateInstallationBehavior: @escaping AsyncBehavior = {},
        tokenOperationBehavior: TokenBehavior? = nil,
        linkInstallationBehavior: @escaping AsyncBehavior = {},
        deleteAccountBehavior: @escaping AsyncBehavior = {},
        deletionStatusBehavior: DeletionStatusBehavior? = nil,
        accountBehavior: AccountBehavior? = nil,
        outboxBehavior: @escaping OutboxBehavior = { _, _ in },
        coverSubmissionBehavior: @escaping CoverSubmissionBehavior = { _ in },
        dealSubmissionBehavior: @escaping DealSubmissionBehavior = { _ in },
        dealSuggestionsBehavior: DealSuggestionsBehavior? = nil,
        dealsBehavior: DealsBehavior? = nil,
        venueCoverBehavior: VenueCoverBehavior? = nil,
        handbookPageBehavior: HandbookPageBehavior? = nil,
        premiumAfterAuthentication: Bool = true,
        canonicalFixtureClient: LiveAPIClient? = nil
    ) {
        self.createInstallationBehavior = createInstallationBehavior
        self.currentInstallationBehavior = currentInstallationBehavior
        self.rotateInstallationBehavior = rotateInstallationBehavior
        self.tokenOperationBehavior = tokenOperationBehavior
        self.linkInstallationBehavior = linkInstallationBehavior
        self.deleteAccountBehavior = deleteAccountBehavior
        self.deletionStatusBehavior = deletionStatusBehavior ?? { _ in false }
        self.accountBehavior = accountBehavior
        self.outboxBehavior = outboxBehavior
        self.coverSubmissionBehavior = coverSubmissionBehavior
        self.dealSubmissionBehavior = dealSubmissionBehavior
        self.dealSuggestionsBehavior = dealSuggestionsBehavior
        self.dealsBehavior = dealsBehavior
        self.venueCoverBehavior = venueCoverBehavior
        self.handbookPageBehavior = handbookPageBehavior
        self.premiumAfterAuthentication = premiumAfterAuthentication
        self.canonicalFixtureClient = canonicalFixtureClient
    }

    func status() async throws -> String { "ok" }
    func createInstallation(requestID: String, installationToken: String) async throws -> String {
        installationCount += 1
        try await createInstallationBehavior()
        try await tokenOperationBehavior?(requestID, installationToken, nil)
        return installationToken
    }
    func currentInstallationActorID() async throws -> String {
        installationReadCount += 1
        try await currentInstallationBehavior()
        return "preview-installation-actor"
    }
    func rotateInstallation(requestID: String, replacementToken: String, authorizationToken: String) async throws -> String {
        rotationCount += 1
        try await rotateInstallationBehavior()
        try await tokenOperationBehavior?(requestID, replacementToken, authorizationToken)
        return replacementToken
    }

    func coverBoard(eTag: String?) async throws -> HTTPResult<CoverBoardResponse> {
        if let canonicalFixtureClient { return try await canonicalFixtureClient.coverBoard(eTag: eTag) }
        return HTTPResult(value: .fixture, eTag: "preview-cover-v1", notModified: false)
    }

    func venueCover(id: String) async throws -> VenueCoverResponse {
        if let venueCoverBehavior { return try await venueCoverBehavior(id) }
        if let canonicalFixtureClient { return try await canonicalFixtureClient.venueCover(id: id) }
        let card = CoverBoardResponse.fixture.venues.first(where: { $0.venue.id == id }) ?? CoverBoardResponse.fixture.venues[0]
        return VenueCoverResponse(
            venue: card.venue,
            cover: card.cover,
            recentReports: .fixture,
            vibes: card.vibes,
            deals: DealsResponse.fixture.venues.first(where: { $0.venue.id == id })?.deals ?? []
        )
    }

    func coverHistory(venueID: String) async throws -> CoverHistoryResponse {
        if let canonicalFixtureClient { return try await canonicalFixtureClient.coverHistory(venueID: venueID) }
        let venue = CoverBoardResponse.fixture.venues.first(where: { $0.venue.id == venueID })?.venue
            ?? CoverBoardResponse.fixture.venues[0].venue
        return CoverHistoryResponse(
            venue: venue,
            serviceDate: ServiceNight.currentServiceDate,
            accessTier: .limited,
            windowStart: Date.now.addingTimeInterval(-7 * 24 * 60 * 60),
            hasMore: false,
            reports: .fixture
        )
    }

    func timeMachine(venueID: String, target: Date) async throws -> TimeMachineResponse {
        if let canonicalFixtureClient {
            return try await canonicalFixtureClient.timeMachine(venueID: venueID, target: target)
        }
        let venue = CoverBoardResponse.fixture.venues.first(where: { $0.venue.id == venueID })?.venue
            ?? CoverBoardResponse.fixture.venues[0].venue
        return TimeMachineResponse(
            venue: venue,
            targetTime: target,
            knowledgeCutoff: .now,
            mode: target < .now ? .past : .future,
            cover: CoverDecision(
                price: target < .now ? .single(1_000) : .range(1_000, 1_500),
                source: .historical,
                freshnessSeconds: nil,
                decisionId: "preview-time-machine",
                status: "historical"
            )
        )
    }

    func submitCover(_ request: CoverSubmissionRequest) async throws -> SubmissionReceipt {
        try await coverSubmissionBehavior(request)
        try await Task.sleep(for: .milliseconds(250))
        return SubmissionReceipt(submissionId: request.submissionId, acceptedAt: .now, requestId: "preview-request")
    }

    func deals(eTag: String?) async throws -> HTTPResult<DealsResponse> {
        if let dealsBehavior { return try await dealsBehavior(eTag) }
        if let canonicalFixtureClient { return try await canonicalFixtureClient.deals(eTag: eTag) }
        return HTTPResult(value: .fixture, eTag: "preview-deals-v1", notModified: false)
    }

    func venueDeals(venueID: String, eTag: String?) async throws -> HTTPResult<VenueDeals> {
        if let canonicalFixtureClient {
            return try await canonicalFixtureClient.venueDeals(venueID: venueID, eTag: eTag)
        }
        let venue = DealsResponse.fixture.venues.first(where: { $0.venue.id == venueID })
            ?? DealsResponse.fixture.venues[0]
        return HTTPResult(value: venue, eTag: "preview-venue-deals-v1", notModified: false)
    }

    func dealSuggestions(query: String, venueID: String?) async throws -> [DealSuggestion] {
        if let dealSuggestionsBehavior {
            return try await dealSuggestionsBehavior(query, venueID)
        }
        if let canonicalFixtureClient {
            return try await canonicalFixtureClient.dealSuggestions(query: query, venueID: venueID)
        }
        let registry = DealsResponse.fixture.venues.flatMap(\.deals) + [
            Deal(id: "suggestion-wells-pint", familyId: "wells", category: .drink, name: "Well Drinks", price: .single(400), serving: "Pint", timing: .after("9:00 PM"), status: "current"),
            Deal(id: "suggestion-tacos", familyId: "tacos", category: .food, name: "Taco Basket", price: .single(500), serving: "Basket", timing: .before("10:00 PM"), status: "current"),
        ]
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let matches = trimmed.isEmpty ? registry : registry.filter {
            $0.name.localizedCaseInsensitiveContains(trimmed)
        }
        return Array(matches.prefix(6)).enumerated().map { index, deal in
            DealSuggestion(
                deal: deal,
                sourceScope: index.isMultiple(of: 2) ? "venue" : "global",
                lastSeenServiceDateLocal: "2026-08-09",
                matchedSource: index == 0 && !trimmed.isEmpty ? .alias : nil,
                matchedText: index == 0 && !trimmed.isEmpty ? "Happy Hour Rail Drinks" : nil
            )
        }
    }

    func submitDeal(_ request: DealEvidenceRequest) async throws -> SubmissionReceipt {
        try await dealSubmissionBehavior(request)
        try await Task.sleep(for: .milliseconds(250))
        return SubmissionReceipt(submissionId: request.submissionId, acceptedAt: .now, requestId: "preview-request")
    }

    func handbook(eTag: String?) async throws -> HTTPResult<[HandbookPageSummary]> {
        HTTPResult(value: .fixture, eTag: "preview-handbook-v1", notModified: false)
    }

    func handbookPage(slug: String) async throws -> HandbookPage {
        if let handbookPageBehavior { return try await handbookPageBehavior(slug) }
        return HandbookPage(
            id: slug,
            slug: slug,
            title: slug == "cover-basics" ? "Cover basics" : "A safer night out",
            summary: "A quick guide for Green Street nights.",
            bodyMarkdown: "## Keep it simple\n\nCover can change during a service night. Check the source and report what you actually observe.\n\n## Look out for each other\n\nStay with friends, charge your phone, and arrange a safe ride home.",
            updatedAt: .now
        )
    }

    func requestEmailCode(email: String, intent: EmailCodeIntent) async throws -> EmailCodeChallenge {
        EmailCodeChallenge(sessionToken: "preview-challenge", intent: intent)
    }

    func resendEmailCode(intent: EmailCodeIntent) async throws { resendCount += 1 }

    func verifyEmailCode(code: String, intent: EmailCodeIntent) async throws -> AuthSessionResponse {
        guard code.filter(\.isLetter).uppercased() == "BCDFGHJK" else {
            throw APIClientError.server(APIErrorPayload(code: "invalid_code", message: "That code was not accepted.", requestId: "preview"), status: 400)
        }
        let account = AccountSummary(id: "11111111-1111-4111-8111-111111111111", email: "alex@example.com", firstName: "Alex", graduationYear: 2027)
        self.account = account
        premium = premiumAfterAuthentication
        return AuthSessionResponse(account: account, sessionToken: "preview-session-token")
    }

    func me() async throws -> AccountSummary {
        accountReadCount += 1
        if let accountBehavior { return try await accountBehavior() }
        guard let account else { throw APIClientError.unauthorized }
        return account
    }

    func signOut() async throws { account = nil; premium = false }
    func deleteAccount(requestID: String) async throws {
        deletionCount += 1
        try await deleteAccountBehavior()
        completedDeletionRequests.insert(requestID)
        account = nil
        premium = false
    }
    func accountDeletionCompleted(requestID: String) async throws -> Bool {
        if completedDeletionRequests.contains(requestID) { return true }
        return try await deletionStatusBehavior(requestID)
    }
    func linkInstallation(requestID: String) async throws {
        linkCount += 1
        try await linkInstallationBehavior()
    }
    func entitlements() async throws -> EntitlementSummary { EntitlementSummary(premium: premium, expiresAt: nil) }
    func sendOutbox(kind: OutboxKind, payload: Data) async throws {
        outboxCount += 1
        try await outboxBehavior(kind, payload)
    }
}

extension CoverBoardResponse {
    static let fixture = CoverBoardResponse(
        serviceDate: "2026-08-12",
        generatedAt: .now,
        venues: [
            CoverVenueCard(
                venue: Venue(id: "kams", slug: "kams", name: "KAMS", address: "102 E Green St", openedYear: 1933),
                cover: CoverDecision(price: .single(2_000), source: .live, freshnessSeconds: 8 * 60, decisionId: "cover-kams", status: "live"),
                recentReportCount: 2,
                vibes: VibeSummary(lineLength: "long", lineSpeed: "fast", crowdLevel: nil)
            ),
            CoverVenueCard(
                venue: Venue(id: "joes", slug: "joes", name: "Joe’s", address: "706 S 5th St", openedYear: 1991),
                cover: CoverDecision(price: .single(1_000), source: .historical, freshnessSeconds: nil, decisionId: "cover-joes", status: "historical"),
                recentReportCount: 0,
                vibes: .empty
            ),
            CoverVenueCard(
                venue: Venue(id: "brothers", slug: "brothers", name: "Brothers", address: "613 E Green St", openedYear: 2023),
                cover: CoverDecision(price: .range(500, 1_000), source: .mixed, freshnessSeconds: 17 * 60, decisionId: "cover-brothers", status: "mixed"),
                recentReportCount: 3,
                vibes: VibeSummary(lineLength: "medium", lineSpeed: "normal", crowdLevel: "busy")
            ),
            CoverVenueCard(
                venue: Venue(id: "red-lion", slug: "red-lion", name: "Red Lion", address: "211 E Green St", openedYear: 2010),
                cover: CoverDecision(price: .unavailable, source: .unavailable, freshnessSeconds: nil, decisionId: nil, status: "unavailable"),
                recentReportCount: 0,
                vibes: .empty
            ),
        ]
    )
}

extension Array where Element == RecentCoverReport {
    static let fixture: [RecentCoverReport] = [
        RecentCoverReport(id: "r1", price: .single(2_000), observedAt: .now.addingTimeInterval(-480), sourceLabel: "Community", locationContext: "Near the venue", vibes: ["Long line", "Fast line"]),
        RecentCoverReport(id: "r2", price: .single(2_000), observedAt: .now.addingTimeInterval(-1_020), sourceLabel: "Community", locationContext: nil, vibes: ["Busy"]),
        RecentCoverReport(id: "r3", price: .single(1_500), observedAt: .now.addingTimeInterval(-2_400), sourceLabel: "Community", locationContext: nil, vibes: []),
        RecentCoverReport(id: "r4", price: nil, observedAt: .now.addingTimeInterval(-2_900), sourceLabel: "Community", locationContext: "Outside", vibes: ["Medium line"]),
        RecentCoverReport(id: "r5", price: .single(1_000), observedAt: .now.addingTimeInterval(-4_500), sourceLabel: "Community", locationContext: nil, vibes: []),
    ]
}

extension DealsResponse {
    static let fixture = DealsResponse(
        serviceDate: "2026-08-12",
        generatedAt: .now,
        venues: [
            VenueDeals(venue: CoverBoardResponse.fixture.venues[0].venue, deals: [
                Deal(id: "d1", familyId: "wells", category: .drink, name: "Well Drinks", price: .single(300), serving: Deal.presentServing(format: "12 oz", unit: "draft"), timing: .allNight, status: "current"),
                Deal(id: "d2", familyId: "pitchers", category: .drink, name: "Blue Guys", price: .single(500), serving: Deal.presentServing(format: "64 oz", unit: "pitcher"), timing: .unknown, status: "likely"),
            ]),
            VenueDeals(venue: CoverBoardResponse.fixture.venues[1].venue, deals: [
                Deal(id: "d3", familyId: "burgers", category: .food, name: "Burger Basket", price: .range(500, 700), serving: Deal.presentServing(format: "Single", unit: "basket"), timing: .before("10:00 PM"), status: "current"),
            ]),
            VenueDeals(venue: CoverBoardResponse.fixture.venues[2].venue, deals: []),
            VenueDeals(venue: CoverBoardResponse.fixture.venues[3].venue, deals: []),
        ]
    )
}

extension Array where Element == HandbookPageSummary {
    static let fixture: [HandbookPageSummary] = [
        HandbookPageSummary(id: "cover-basics", slug: "cover-basics", title: "Cover basics", summary: "What live reports and historical estimates mean.", updatedAt: .now),
        HandbookPageSummary(id: "safer-night", slug: "safer-night", title: "A safer night out", summary: "Simple ways to plan ahead and look out for friends.", updatedAt: .now),
    ]
}
