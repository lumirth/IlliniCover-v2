import Foundation
import Testing
@testable import IlliniCover

@Suite("File-backed cache and outbox", .serialized)
struct DatabaseTests {
    @Test("Local and Preview databases cannot see or drain each other's outbox")
    func deploymentEnvironmentIsolation() async throws {
        let parent = FileManager.default.temporaryDirectory
            .appending(path: "IlliniCoverEnvironmentTests-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        let local = try AppDatabase.production(namespace: "local", baseDirectory: parent)
        let preview = try AppDatabase.production(namespace: "preview", baseDirectory: parent)
        let request = CoverSubmissionRequest(
            submissionId: "local-only-submission",
            venueId: "local-venue",
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: nil,
            cover: CoverObservationRequest(
                priceCents: 500,
                interaction: .manual,
                displayedDecisionId: nil,
                pricePrefilled: false,
                priceTouched: true
            ),
            vibes: []
        )
        try await local.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)

        #expect(try await local.outboxCount() == 1)
        #expect(try await preview.outboxCount() == 0)

        let localRelaunch = try AppDatabase.production(namespace: "local", baseDirectory: parent)
        let previewRelaunch = try AppDatabase.production(namespace: "preview", baseDirectory: parent)
        #expect(try await localRelaunch.outboxCount() == 1)
        #expect(try await previewRelaunch.outboxCount() == 0)
    }

    @Test("Cache round trip keeps server and fetch timestamps separate")
    func cacheRoundTrip() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appending(path: "cache.sqlite").path
        let database = try AppDatabase(path: path)
        let fetchedAt = Date(timeIntervalSince1970: 100)
        let generatedAt = Date(timeIntervalSince1970: 50)
        try await database.cache(CoverBoardResponse.fixture, key: "board", etag: "etag", fetchedAt: fetchedAt, serverGeneratedAt: generatedAt)

        let reopened = try AppDatabase(path: path)
        let cached = try #require(try await reopened.cached(CoverBoardResponse.self, key: "board"))
        #expect(cached.0.venues.count == 4)
        #expect(cached.1.etag == "etag")
        #expect(cached.1.fetchedAt == fetchedAt)
        #expect(cached.1.serverGeneratedAt == generatedAt)
    }

    @Test("Live acceptance cache and outbox persist across relaunch until explicit reset")
    func liveAcceptanceRelaunchAndReset() async throws {
        let parent = FileManager.default.temporaryDirectory
            .appending(path: "IlliniCoverAcceptanceTests-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        let first = try AppDatabase.liveAcceptance(baseDirectory: parent)
        try await first.cache(CoverBoardResponse.fixture, key: "cover", etag: "acceptance")
        let request = CoverSubmissionRequest(
            submissionId: "acceptance-offline",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: nil,
            cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await first.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)

        let relaunched = try AppDatabase.liveAcceptance(baseDirectory: parent)
        #expect(try await relaunched.cached(CoverBoardResponse.self, key: "cover") != nil)
        #expect(try await relaunched.outboxCount() == 1)

        try await relaunched.resetLocalData()
        let resetRelaunch = try AppDatabase.liveAcceptance(baseDirectory: parent)
        #expect(try await resetRelaunch.cached(CoverBoardResponse.self, key: "cover") == nil)
        #expect(try await resetRelaunch.outboxCount() == 0)
    }

    @Test("Duplicate offline enqueue preserves one idempotent request")
    func outboxIdempotency() async throws {
        let database = try AppDatabase.temporary()
        let request = CoverSubmissionRequest(
            submissionId: UUID().uuidString,
            venueId: UUID().uuidString,
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: nil,
            cover: CoverObservationRequest(priceCents: 2_000, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        #expect(try await database.outboxCount() == 1)
        let entry = try #require(try await database.pendingOutbox().first)
        #expect(entry.observedAt == request.observedAt)
    }

    @Test("Retry backoff is bounded and a manual retry preserves the payload")
    func outboxBackoffAndRetry() async throws {
        let database = try AppDatabase.temporary()
        let request = CoverSubmissionRequest(
            submissionId: "stable-submission",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: .init(latitude: 40.11, longitude: -88.23, accuracyMeters: 20),
            cover: CoverObservationRequest(priceCents: 2_000, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        let failureTime = Date(timeIntervalSince1970: 1_000)
        try await database.markAttempt(id: request.id, failureCode: "offline", now: failureTime)

        #expect(try await database.pendingOutbox(now: failureTime).isEmpty)
        let delayed = try #require(try await database.pendingOutbox(now: failureTime.addingTimeInterval(2)).first)
        #expect(delayed.id == request.submissionId)
        #expect(delayed.observedAt == request.observedAt)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let persisted = try decoder.decode(CoverSubmissionRequest.self, from: delayed.payloadJSON)
        #expect(persisted.submissionId == request.submissionId)
        #expect(persisted.observedAt == request.observedAt)
        #expect(persisted.location == request.location)

        for attempt in 2...8 {
            try await database.markAttempt(
                id: request.id,
                failureCode: "server_503",
                now: failureTime.addingTimeInterval(Double(attempt))
            )
        }
        #expect(try await database.outboxStatus() == OutboxStatus(queued: 0, failed: 1))
        try await database.retryFailedOutbox()
        #expect(try await database.outboxStatus() == OutboxStatus(queued: 1, failed: 0))
        let retried = try #require(try await database.pendingOutbox(now: failureTime).first)
        #expect(retried.payloadJSON == delayed.payloadJSON)
    }

    @Test("Account deletion purge removes queued location and cached private state")
    func privacyPurge() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appending(path: "privacy.sqlite").path
        let database = try AppDatabase(path: path)
        let request = CoverSubmissionRequest(
            submissionId: "location-report",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: .init(latitude: 40.11, longitude: -88.23, accuracyMeters: 8),
            cover: CoverObservationRequest(priceCents: 1_000, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        try await database.cache(EntitlementSummary(premium: true, expiresAt: nil), key: "private-entitlement", etag: nil)

        try await database.resetLocalData()

        let reopened = try AppDatabase(path: path)
        #expect(try await reopened.outboxCount() == 0)
        #expect(try await reopened.cached(EntitlementSummary.self, key: "private-entitlement") == nil)
    }

    @Test("Retryable HTTP 5xx survives process-style database reopen with original evidence")
    func retryableServerFailureSurvivesRelaunch() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appending(path: "retry.sqlite").path
        let database = try AppDatabase(path: path)
        let processor = OutboxProcessor(database: database, api: AlwaysUnavailableOutboxAPI())
        let request = CoverSubmissionRequest(
            submissionId: "server-retry-stable-id",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 987),
            vantagePoint: .outside,
            location: .init(latitude: 40.109, longitude: -88.228, accuracyMeters: 12),
            cover: CoverObservationRequest(priceCents: 2_000, interaction: .manual, displayedDecisionId: "decision", pricePrefilled: true, priceTouched: true),
            vibes: []
        )

        try await processor.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        await processor.drain()

        let relaunched = try AppDatabase(path: path)
        #expect(try await relaunched.outboxStatus() == OutboxStatus(queued: 1, failed: 0))
        let entry = try #require(try await relaunched.pendingOutbox(now: .now.addingTimeInterval(16 * 60)).first)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let restored = try decoder.decode(CoverSubmissionRequest.self, from: entry.payloadJSON)
        #expect(restored.submissionId == request.submissionId)
        #expect(restored.observedAt == request.observedAt)
        #expect(restored.location == request.location)
        #expect(entry.lastError == "server_503")
    }

    @Test("A relaunched drain sends more than one database batch")
    func drainDoesNotStrandRowsAfterFirstBatch() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appending(path: "many.sqlite").path
        let writer = try AppDatabase(path: path)
        for index in 0..<61 {
            let request = CoverSubmissionRequest(
                submissionId: "batch-\(index)",
                venueId: "venue",
                observedAt: Date(timeIntervalSince1970: Double(index)),
                vantagePoint: .outside,
                location: nil,
                cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
                vibes: []
            )
            try await writer.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        }

        let reopened = try AppDatabase(path: path)
        let sender = CountingOutboxAPI()
        let processor = OutboxProcessor(database: reopened, api: sender)
        await processor.drain()

        #expect(try await reopened.outboxCount() == 0)
        #expect(await sender.count == 61)
    }

    @Test("Permanent client failures remain visible without blocking later reports")
    func permanentFailureDoesNotBlockIndependentRows() async throws {
        let database = try AppDatabase.temporary()
        for index in 0..<2 {
            let request = CoverSubmissionRequest(
                submissionId: "permanent-\(index)", venueId: "venue",
                observedAt: Date(timeIntervalSince1970: Double(index)), vantagePoint: .outside,
                location: nil,
                cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
                vibes: []
            )
            try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        }
        let sender = FirstRejectedOutboxAPI()
        await OutboxProcessor(database: database, api: sender).drain()

        #expect(try await database.outboxStatus() == OutboxStatus(queued: 0, failed: 1))
        #expect(await sender.count == 2)
    }

    @Test("Permanent validation failures can be inspected and safely discarded")
    func permanentFailureRecovery() async throws {
        let database = try AppDatabase.temporary()
        let request = CoverSubmissionRequest(
            submissionId: "invalid-saved-report", venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 123), vantagePoint: .outside,
            location: nil,
            cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        try await database.markPermanentFailure(id: request.id, failureCode: "server_422")

        let summary = try #require(try await database.failedOutboxSummaries().first)
        #expect(summary.kind == .cover)
        #expect(summary.observedAt == request.observedAt)
        #expect(summary.failureCode == "server_422")
        #expect(!summary.canRetryUnchanged)

        try await database.retryFailedOutbox()
        #expect(try await database.outboxStatus().failed == 1)
        try await database.discardFailedOutbox()
        #expect(try await database.outboxCount() == 0)
    }
}

private actor AlwaysUnavailableOutboxAPI: OutboxSending {
    func sendOutbox(kind: OutboxKind, payload: Data) async throws {
        throw APIClientError.server(
            APIErrorPayload(code: "temporarily_unavailable", message: "Try again later.", requestId: "server-request"),
            status: 503
        )
    }
}

private actor CountingOutboxAPI: OutboxSending {
    private(set) var count = 0
    func sendOutbox(kind: OutboxKind, payload: Data) async throws { count += 1 }
}

private actor FirstRejectedOutboxAPI: OutboxSending {
    private(set) var count = 0
    func sendOutbox(kind: OutboxKind, payload: Data) async throws {
        count += 1
        if count == 1 {
            throw APIClientError.server(
                APIErrorPayload(code: "invalid_evidence", message: "Invalid", requestId: "request"),
                status: 422
            )
        }
    }
}
