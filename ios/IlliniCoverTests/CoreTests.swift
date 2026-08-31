import CoreLocation
import XCTest
@testable import IlliniCover

@MainActor
final class CoreTests: XCTestCase {
    func testCoverPricePresentationAndNormalization() {
        XCTAssertEqual(CoverPrice(amountCents: 1_000, kind: "single").displayText, "$10")
        XCTAssertEqual(CoverPrice(highCents: 1_000, kind: "range", lowCents: 500).displayText, "$5–$10")
        XCTAssertEqual(CoverPrice.normalizedReportCents(751), 500)
        XCTAssertEqual(CoverPrice.normalizedReportCents(-1), 0)
        XCTAssertEqual(CoverPrice.normalizedReportCents(9_999), 7_000)
    }

    func testWireVocabularyMatchesProductContract() throws {
        XCTAssertEqual(VibeInput.choices[.lineLength]?.map { $0.value }, ["short", "medium", "long"])
        XCTAssertEqual(VibeInput.choices[.lineSpeed]?.map { $0.value }, ["slow", "normal", "fast"])
        XCTAssertEqual(VibeInput.choices[.crowdLevel]?.map { $0.value }, ["quiet", "busy", "packed"])
        XCTAssertEqual(SubmissionOutcome.sent.dealNotice(for: .denyPresent), "Deal report sent")

        let data = Data(#"{"entitlements":[{"expiresAt":null,"identifier":"premium","isActive":true}]}"#.utf8)
        XCTAssertTrue(try JSONDecoder().decode(EntitlementSummary.self, from: data).premium)
        XCTAssertFalse(EntitlementSummary(entitlements: [.init(expiresAt: nil, identifier: "blue", isActive: true)]).premium)

        let first = Self.suggestion(timing: nil, whileSuppliesLast: false)
        let second = Self.suggestion(timing: "Until 10 PM", whileSuppliesLast: false)
        XCTAssertNotEqual(first.id, second.id)
        let combined = Deal(canonicalFamilyId: "family", category: "drink", discountPercent: nil,
                            displayName: "Deal", id: "deal", latestActivityAt: nil, priceCents: 500,
                            priceHighCents: nil, priceKind: "absolute", priceLowCents: nil,
                            servingFormat: "can", status: "active", timingDescription: "Until 10 PM",
                            timingKnown: true, unit: "12 oz", whileSuppliesLast: true)
        XCTAssertEqual(combined.timingText, "Until 10 PM · While supplies last")

        let unavailable = Data(#"{"computedAt":0,"knowledgeCutoff":1,"price":{"kind":"single"},"source":"unavailable","freshnessSeconds":null,"status":"unavailable","targetTime":2}"#.utf8)
        let decoded = try JSONDecoder().decode(CoverDecision.self, from: unavailable)
        XCTAssertNil(decoded.evidenceText)
        XCTAssertEqual(try JSONDecoder().decode(CoverDecision.self, from: JSONEncoder().encode(decoded)), decoded)
        let price = CoverPrice(amountCents: 500, kind: "single")
        let current = CoverDecision(computedAt: Date(timeIntervalSince1970: 1_000), knowledgeCutoff: Date(timeIntervalSince1970: 990),
                                    price: price, source: "live", freshnessSeconds: 30, status: "live",
                                    targetTime: Date(timeIntervalSince1970: 1_000))
        XCTAssertEqual(current.evidenceText(at: Date(timeIntervalSince1970: 1_000)), "Reported just now")
        XCTAssertEqual(current.evidenceText(at: Date(timeIntervalSince1970: 1_120)), "Reported 2m ago")
        XCTAssertEqual(current.evidenceText(at: Date(timeIntervalSince1970: 173_800)), "Reported 2d ago")
        let label = { CoverDecision(computedAt: .distantPast, knowledgeCutoff: .distantPast, price: price, source: $1,
                                    freshnessSeconds: 30, status: $0, targetTime: .distantPast).presentationSourceLabel }
        XCTAssertEqual(label("unusual", "live"), "Unusual")
        XCTAssertEqual(label("live_mixed", "mixed"), "Mixed")
        XCTAssertEqual(label("reconstructed", "historical"), "Historical")
        XCTAssertEqual(label("reconstructed_mixed", "historical"), "Historical · Mixed")
        XCTAssertEqual(label("advertised_conflict", "mixed"), "Mixed · Advertised differs")
    }

    func testDisplayedContextIsPreservedWithoutReceiptIdentity() throws {
        let input = CoverInput(
            interaction: .correct,
            priceCents: 1_500,
            pricePrefilled: true,
            priceTouched: true,
            displayedSource: "historical",
            displayedPriceKind: "range",
            displayedAmountCents: nil,
            displayedLowCents: 500,
            displayedHighCents: 1_000
        )
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(input)) as? [String: Any])
        XCTAssertEqual(json["displayedSource"] as? String, "historical")
        XCTAssertEqual(json["displayedLowCents"] as? Int, 500)
        XCTAssertNil(json["displayedDecisionId"])
    }

    func testChicagoFiveAMServiceNightCutoff() throws {
        let formatter = ISO8601DateFormatter()
        let cases = [
            ("2026-03-08T09:59:59Z", "2026-03-07"), ("2026-03-08T10:00:00Z", "2026-03-08"),
            ("2026-11-01T10:59:59Z", "2026-10-31"), ("2026-11-01T11:00:00Z", "2026-11-01"),
            ("2026-08-30T09:59:59Z", "2026-08-29"), ("2026-08-30T10:00:00Z", "2026-08-30"),
        ]
        for (timestamp, expected) in cases {
            XCTAssertEqual(ServiceNight.serviceDate(containing: try XCTUnwrap(formatter.date(from: timestamp))), expected)
        }
    }

    func testDeepLinksAcceptOnlyVenueLinks() {
        XCTAssertEqual(DeepLink.venueID(URL(string: "illinicover://venue/kams")!), "kams")
        XCTAssertNil(DeepLink.venueID(URL(string: "https://example.com/venue/kams")!))
    }

    func testLocationRejectsInvalidOrStaleObservations() {
        let now = Date(timeIntervalSince1970: 1_000)
        XCTAssertNil(LocationClient.submissionLocation(from: CLLocation(latitude: 100, longitude: 200)))
        let makeLocation = { (timestamp: Date) in
            CLLocation(coordinate: .init(latitude: 40.11, longitude: -88.23), altitude: 0,
                       horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: timestamp)
        }
        let valid = LocationClient.submissionLocation(from: makeLocation(now.addingTimeInterval(-60)), now: now)
        XCTAssertEqual(valid?.latitude, 40.11)
        XCTAssertNil(LocationClient.submissionLocation(from: makeLocation(now.addingTimeInterval(-61)), now: now))
        XCTAssertNil(LocationClient.submissionLocation(from: makeLocation(now.addingTimeInterval(6)), now: now))
    }

    func testEnvironmentOriginsFailClosed() throws {
        let local = try AppConfiguration.validated([
            "ICAPIBaseURL": "http://127.0.0.1:8000",
            "ICEnvironment": "local",
            "ICRevenueCatAPIKey": AppConfiguration.testStoreKey,
        ], bundle: AppConfiguration.developmentBundle)
        XCTAssertEqual(local.deployment, .local)
        XCTAssertThrowsError(try AppConfiguration.validated([
            "ICAPIBaseURL": "https://evil.example",
            "ICEnvironment": "production",
            "ICRevenueCatAPIKey": "appl_validlookingkey",
        ], bundle: AppConfiguration.productionBundle))
    }

    func testCacheAndOutboxLifecycle() async throws {
        let database = try AppDatabase.temporary()
        let venue = Venue(id: "1", slug: "one", name: "One", address: "", openedYear: nil)
        try await database.cache(venue, key: "venue")
        let cached = try await database.cached(Venue.self, key: "venue")
        XCTAssertEqual(cached?.0, venue)

        let request = CoverSubmissionRequest(
            clientPlatform: "ios",
            cover: nil,
            entryPoint: "test",
            location: nil,
            observedAt: .now,
            submissionId: "submission",
            vantagePoint: .unknown,
            venueId: venue.id,
            vibes: [.init(dimension: .crowdLevel, value: "busy")]
        )
        try await database.enqueue(id: request.submissionId, kind: .cover, observedAt: request.observedAt, value: request)
        var status = try await database.outboxStatus()
        XCTAssertEqual(status, .init(queued: 1, failed: 0))
        try await database.fail(id: request.submissionId, error: "invalid")
        status = try await database.outboxStatus()
        XCTAssertEqual(status, .init(queued: 0, failed: 1))
        try await database.retryFailed()
        let pending = try await database.pendingOutbox()
        XCTAssertEqual(pending.map(\.id), [request.submissionId])
        try await database.resetLocalData()
        status = try await database.outboxStatus()
        let erased = try await database.cached(Venue.self, key: "venue")
        XCTAssertEqual(status, .empty)
        XCTAssertNil(erased)
    }

    func testProductionDatabaseDoesNotEraseUnreadableData() throws {
        let namespace = "corrupt-test-\(UUID())"
        let parent = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let path = parent.appending(path: "IlliniCover/\(namespace).sqlite")
        try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        let sentinel = Data("not a database".utf8)
        try sentinel.write(to: path)
        defer { for suffix in ["", "-wal", "-shm"] { try? FileManager.default.removeItem(atPath: path.path + suffix) } }
        XCTAssertThrowsError(try AppDatabase.production(namespace: namespace))
        XCTAssertEqual(try Data(contentsOf: path), sentinel)
    }

    func testKeychainRoundTripAndPurge() async throws {
        let store = CredentialStore(service: "com.illinicover.tests.\(UUID())")
        try await store.write("secret", for: .sessionToken)
        var value = try await store.read(.sessionToken)
        XCTAssertEqual(value, "secret")
        try await store.deleteAll()
        value = try await store.read(.sessionToken)
        XCTAssertNil(value)
    }

    func testInvalidGuestInstallationPreservesOfflineReportsAndRetriesCurrentSubmission() async throws {
        StubURLProtocol.reset(.installationRecovery)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }

        let credentials = CredentialStore(service: "com.illinicover.recovery-tests.\(UUID())")
        let staleToken = "ic_install_" + String(repeating: "s", count: 43)
        try await credentials.write(staleToken, for: .installationToken)
        let database = try AppDatabase.temporary()
        let venue = Venue(id: "venue", slug: "venue", name: "Venue", address: "", openedYear: nil)
        try await database.cache(venue, key: "private-cache")
        let old = Self.report(id: "old", venueID: venue.id)
        try await database.enqueue(id: old.submissionId, kind: .cover, observedAt: old.observedAt, value: old)

        let config = try AppConfiguration.validated([
            "ICAPIBaseURL": "http://127.0.0.1:8000",
            "ICEnvironment": "local",
            "ICRevenueCatAPIKey": AppConfiguration.testStoreKey,
        ], bundle: AppConfiguration.developmentBundle)
        let defaultsName = "com.illinicover.recovery-defaults.\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: defaultsName))
        defer { defaults.removePersistentDomain(forName: defaultsName) }
        let api = LiveAPIClient(baseURL: config.apiBaseURL, credentials: credentials, session: session)
        let environment = AppEnvironment(api: api, database: database, credentials: credentials, settings: AppSettings(defaults: defaults), configuration: config)
        try await environment.ensureInstallation()
        environment.isBootstrapping = false

        let current = Self.report(id: "current", venueID: venue.id)
        let outcome = await environment.submitCover(current)
        XCTAssertEqual(outcome, .sent)
        await environment.outbox.drain()

        let requests = StubURLProtocol.requests()
        XCTAssertEqual(requests.map { $0.url?.path }, ["/api/cover-submissions", "/api/installations", "/api/cover-submissions", "/api/cover-submissions"])
        let submissions = requests.filter { $0.url?.path == "/api/cover-submissions" }
        let freshToken = try await credentials.read(.installationToken)
        XCTAssertEqual(submissions.first?.value(forHTTPHeaderField: "X-Installation-Token"), staleToken)
        XCTAssertEqual(submissions.last?.value(forHTTPHeaderField: "X-Installation-Token"), freshToken)
        XCTAssertNotEqual(freshToken, staleToken)
        let sessionToken = try await credentials.read(.sessionToken)
        let outboxStatus = try await database.outboxStatus()
        let cached = try await database.cached(Venue.self, key: "private-cache")
        XCTAssertNil(sessionToken)
        XCTAssertEqual(outboxStatus, .empty)
        XCTAssertNotNil(cached)
        let submissionIDs = try zip(requests, StubURLProtocol.bodies()).compactMap { request, body -> String? in
            guard request.url?.path == "/api/cover-submissions" else { return nil }
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(body)) as? [String: Any])
            return try XCTUnwrap(json["submissionId"] as? String)
        }
        XCTAssertEqual(submissionIDs, [current.submissionId, current.submissionId, old.submissionId])
    }

    func testUnauthorizedDeletionRetainsLocalAccountState() async throws {
        let harness = try await deletionHarness(.deleteUnauthorized)
        defer { harness.session.invalidateAndCancel() }

        do { try await harness.environment.deleteAccount(); XCTFail("Unauthorized deletion must fail") }
        catch APIClientError.unauthorized { }

        let sessionToken = try await harness.credentials.read(.sessionToken)
        let cached = try await harness.database.cached(Venue.self, key: "cache")
        XCTAssertEqual(sessionToken, "session")
        XCTAssertEqual(harness.environment.account?.id, "account")
        XCTAssertFalse(harness.environment.settings.accountDeletionUncertain)
        XCTAssertNotNil(cached)

        harness.environment.settings.accountDeletionUncertain = true
        do { try await harness.environment.didAuthenticate(.init(displayName: "Other", email: "other@example.com", id: "other")) }
        catch APIClientError.unauthorized { }
        XCTAssertFalse(harness.environment.settings.accountDeletionUncertain)
    }

    func testAmbiguousDeletionThenUnauthorizedPurgesLocalState() async throws {
        let harness = try await deletionHarness(.deleteAmbiguous)
        defer { harness.session.invalidateAndCancel() }
        do { try await harness.environment.deleteAccount(); XCTFail("Ambiguous deletion must surface") }
        catch APIClientError.server(_, 503) { }
        XCTAssertTrue(harness.environment.settings.accountDeletionUncertain)
        XCTAssertTrue(AppSettings(defaults: harness.defaults).accountDeletionUncertain)
        XCTAssertEqual(harness.environment.account?.id, "account")
        harness.environment.settings.reset()
        XCTAssertTrue(harness.environment.settings.accountDeletionUncertain)

        try await harness.environment.deleteAccount()
        try await assertDeletionPurged(harness)
    }

    func testSuccessfulDeletionPurgesLocalState() async throws {
        let harness = try await deletionHarness(.deleteSuccess)
        defer { harness.session.invalidateAndCancel() }
        try await harness.environment.deleteAccount()
        try await assertDeletionPurged(harness)
    }

    func testDeletionCheckpointCompletesCleanupAfterRemoteAccountIsGone() async throws {
        let harness = try await deletionHarness(.bootstrapDeleted)
        defer { harness.session.invalidateAndCancel() }
        harness.environment.settings.accountDeletionUncertain = true

        try await harness.environment.deleteAccount()

        try await assertDeletionPurged(harness)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, ["/api/me", "/api/installations"])
    }

    func testBootstrapCompletesUncertainRemoteDeletion() async throws {
        let harness = try await deletionHarness(.bootstrapDeleted)
        defer { harness.session.invalidateAndCancel() }
        harness.environment.settings.accountDeletionUncertain = true
        await harness.environment.bootstrap()
        try await assertDeletionPurged(harness)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, ["/api/me", "/api/installations"])
    }

    func testBootstrapClearsUncertaintyWhenAccountStillExists() async throws {
        let harness = try await deletionHarness(.bootstrapAccountSurvives)
        defer { harness.session.invalidateAndCancel() }
        harness.environment.settings.accountDeletionUncertain = true
        await harness.environment.bootstrap()
        XCTAssertEqual(harness.environment.account?.id, "account")
        XCTAssertFalse(harness.environment.settings.accountDeletionUncertain)
        let sessionToken = try await harness.credentials.read(.sessionToken)
        let cached = try await harness.database.cached(Venue.self, key: "cache")
        XCTAssertEqual(sessionToken, "session")
        XCTAssertNotNil(cached)
    }

    func testBootstrapFinishesPartialDeletionWithoutSession() async throws {
        let harness = try await deletionHarness(.bootstrapDeleted)
        defer { harness.session.invalidateAndCancel() }
        harness.environment.settings.accountDeletionUncertain = true
        try await harness.credentials.write("challenge", for: .emailChallengeToken)
        try await harness.credentials.delete(.sessionToken)

        await harness.environment.bootstrap()

        try await assertDeletionPurged(harness)
        let challengeToken = try await harness.credentials.read(.emailChallengeToken)
        XCTAssertNil(challengeToken)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, ["/api/installations"])
    }

    func testAllauthChallengeRotationSurvivesResendAndWrongCode() async throws {
        StubURLProtocol.reset(.authRotation)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let credentials = CredentialStore(service: "com.illinicover.auth-tests.\(UUID())")
        try await credentials.write("challenge-1", for: .emailChallengeToken)
        let api = LiveAPIClient(baseURL: URL(string: "http://127.0.0.1:8000")!, credentials: credentials, session: session)

        try await api.resendEmailCode(.signIn)
        var token = try await credentials.read(.emailChallengeToken)
        XCTAssertEqual(token, "challenge-2")
        do { _ = try await api.verifyEmailCode("wrong", intent: .signIn); XCTFail("Wrong code must fail") } catch { }
        token = try await credentials.read(.emailChallengeToken)
        XCTAssertEqual(token, "challenge-3")
        let response = try await api.verifyEmailCode("correct", intent: .signIn)
        XCTAssertEqual(response.account.email, "person@example.com")
        let sessionToken = try await credentials.read(.sessionToken)
        token = try await credentials.read(.emailChallengeToken)
        XCTAssertEqual(sessionToken, "session-4")
        XCTAssertNil(token)

        let headers = StubURLProtocol.requests().map { $0.value(forHTTPHeaderField: "X-Session-Token") }
        XCTAssertEqual(headers, ["challenge-1", "challenge-2", "challenge-3"])
    }

    func testAuthenticatedBootstrapRepairsDeferredInstallationLink() async throws {
        let harness = try await environmentHarness(.authLinkRecovery)
        defer { harness.session.invalidateAndCancel() }
        try await harness.credentials.write("challenge", for: .emailChallengeToken)
        try await harness.credentials.write("ic_install_" + String(repeating: "l", count: 43), for: .installationToken)

        let response = try await harness.environment.api.verifyEmailCode("123456", intent: .signIn)
        try await harness.environment.didAuthenticate(response.account)
        XCTAssertEqual(harness.environment.account?.id, "account")
        XCTAssertNotNil(harness.environment.globalNotice)

        await harness.environment.bootstrap()
        XCTAssertNil(harness.environment.globalNotice)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, [
            "/_allauth/app/v1/auth/code/confirm", "/api/me/link-installation", "/api/me/entitlements",
            "/api/me", "/api/me/link-installation", "/api/me/entitlements",
        ])
    }

    func testSigningIntoAnotherAccountReplacesLinkedInstallation() async throws {
        let harness = try await environmentHarness(.accountSwitch)
        defer { harness.session.invalidateAndCancel() }
        let old = "ic_install_" + String(repeating: "x", count: 43)
        try await harness.credentials.write(old, for: .installationToken)
        try await harness.credentials.write("expired-a", for: .sessionToken)
        try await harness.database.cache(Venue(id: "public", slug: "public", name: "Public", address: "", openedYear: nil), key: "public")

        await harness.environment.bootstrap()
        try await harness.credentials.write("challenge-b", for: .emailChallengeToken)
        let response = try await harness.environment.api.verifyEmailCode("123456", intent: .signIn)
        try await harness.environment.didAuthenticate(response.account)

        XCTAssertEqual(harness.environment.account?.id, "account-b")
        XCTAssertFalse(harness.environment.reportingReady)
        XCTAssertNotNil(harness.environment.globalNotice)
        let blocked = await harness.environment.submitCover(Self.report(id: "blocked", venueID: "venue"))
        let deferredToken = try await harness.credentials.read(.installationToken)
        XCTAssertEqual(blocked, .failed)
        XCTAssertEqual(deferredToken, old)

        await harness.environment.didEnterForeground()

        let sessionToken = try await harness.credentials.read(.sessionToken)
        let installationToken = try await harness.credentials.read(.installationToken)
        let cached = try await harness.database.cached(Venue.self, key: "public")
        XCTAssertEqual(harness.environment.account?.id, "account-b")
        XCTAssertEqual(sessionToken, "session-b")
        XCTAssertNotEqual(installationToken, old)
        XCTAssertNotNil(cached)
        XCTAssertTrue(harness.environment.reportingReady)
        XCTAssertNil(harness.environment.globalNotice)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, [
            "/api/me", "/_allauth/app/v1/auth/code/confirm", "/api/me/link-installation",
            "/api/installations/rotate", "/api/me/entitlements", "/api/me",
            "/api/me/link-installation", "/api/installations/rotate",
            "/api/me/link-installation", "/api/me/entitlements",
        ])
    }

    func testQueuedReportDrainsWithRFC3339WireDate() async throws {
        let harness = try await environmentHarness(.outboxDrain)
        defer { harness.session.invalidateAndCancel() }
        try await harness.credentials.write("ic_install_" + String(repeating: "q", count: 43), for: .installationToken)
        let report = Self.report(id: "queued", venueID: "venue", observedAt: Date(timeIntervalSince1970: 1_000))
        try await harness.database.enqueue(id: report.submissionId, kind: .cover, observedAt: report.observedAt, value: report)

        await harness.environment.outbox.resume()
        await harness.environment.outbox.drain()

        let status = try await harness.database.outboxStatus()
        XCTAssertEqual(status, .empty)
        let body = try XCTUnwrap(StubURLProtocol.bodies().first.flatMap { $0 })
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(json["observedAt"] as? String, "1970-01-01T00:16:40.000Z")
    }

    func testLostGuestRotationStillClearsQueuedReportsAndCache() async throws {
        let harness = try await environmentHarness(.signOutRotationConflict)
        defer { harness.session.invalidateAndCancel() }
        let old = "ic_install_" + String(repeating: "g", count: 43)
        try await harness.credentials.write(old, for: .installationToken)
        try await harness.database.cache(Venue(id: "venue", slug: "venue", name: "Venue", address: "", openedYear: nil), key: "cover")
        let report = Self.report(id: "queued-for-erasure", venueID: "venue")
        try await harness.database.enqueue(id: report.submissionId, kind: .cover, observedAt: report.observedAt, value: report)

        try await harness.environment.rotateGuestActor()

        let replacement = try await harness.credentials.read(.installationToken)
        let cached = try await harness.database.cached(Venue.self, key: "cover")
        let status = try await harness.database.outboxStatus()
        XCTAssertNotEqual(replacement, old)
        XCTAssertNil(cached)
        XCTAssertEqual(status, .empty)
        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, ["/api/installations/rotate", "/api/installations"])
    }

    func testSignOutRotatesBeforeLogoutAndPreservesPendingReports() async throws {
        StubURLProtocol.reset(.signOut)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let credentials = CredentialStore(service: "com.illinicover.signout-tests.\(UUID())")
        let oldToken = "ic_install_" + String(repeating: "o", count: 43)
        try await credentials.write(oldToken, for: .installationToken)
        try await credentials.write("expired-session", for: .sessionToken)
        let database = try AppDatabase.temporary()
        let venue = Venue(id: "venue", slug: "venue", name: "Venue", address: "", openedYear: nil)
        try await database.cache(venue, key: "public-cache")
        let report = Self.report(id: "pending", venueID: venue.id)
        try await database.enqueue(id: report.submissionId, kind: .cover, observedAt: report.observedAt, value: report)
        let beforeEntries = try await database.pendingOutbox()
        let before = try XCTUnwrap(beforeEntries.first).data
        let config = try AppConfiguration.validated([
            "ICAPIBaseURL": "http://127.0.0.1:8000", "ICEnvironment": "local",
        ], bundle: AppConfiguration.developmentBundle)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "com.illinicover.signout-defaults.\(UUID())"))
        let api = LiveAPIClient(baseURL: config.apiBaseURL, credentials: credentials, session: session)
        let environment = AppEnvironment(api: api, database: database, credentials: credentials, settings: AppSettings(defaults: defaults), configuration: config)
        environment.account = .init(displayName: "Person", email: "person@example.com", id: "account")
        environment.premium = true
        environment.billing.clientPremium = true
        environment.settings.accountDeletionUncertain = true

        try await environment.signOut()

        let requests = StubURLProtocol.requests()
        XCTAssertEqual(requests.map { $0.url?.path }, ["/api/installations/rotate", "/_allauth/app/v1/auth/session"])
        let freshToken = try await credentials.read(.installationToken)
        XCTAssertEqual(requests.first?.value(forHTTPHeaderField: "X-Installation-Token"), oldToken)
        XCTAssertEqual(requests.last?.value(forHTTPHeaderField: "X-Installation-Token"), freshToken)
        XCTAssertNotEqual(freshToken, oldToken)
        let sessionToken = try await credentials.read(.sessionToken)
        XCTAssertNil(sessionToken)
        XCTAssertNil(environment.account)
        XCTAssertFalse(environment.premium)
        XCTAssertFalse(environment.billing.clientPremium)
        XCTAssertFalse(environment.settings.accountDeletionUncertain)
        let pending = try await database.pendingOutbox()
        XCTAssertEqual(pending.map(\.id), [report.submissionId])
        XCTAssertEqual(pending.first?.data, before)
        let cached = try await database.cached(Venue.self, key: "public-cache")
        XCTAssertNotNil(cached)
    }

    func testSignOutRetainsLocalSessionWhenRemoteRevocationIsAmbiguous() async throws {
        let harness = try await environmentHarness(.signOutRevocationAmbiguous)
        defer { harness.session.invalidateAndCancel() }
        let old = "ic_install_" + String(repeating: "a", count: 43)
        try await harness.credentials.write(old, for: .installationToken)
        try await harness.credentials.write("session", for: .sessionToken)
        harness.environment.account = .init(displayName: "Person", email: "person@example.com", id: "account")
        harness.environment.premium = true
        harness.environment.settings.accountDeletionUncertain = true

        do { try await harness.environment.signOut(); XCTFail("Ambiguous revocation must remain retryable") }
        catch APIClientError.server(_, 503) { }

        XCTAssertEqual(StubURLProtocol.requests().map { $0.url?.path }, ["/api/installations/rotate", "/_allauth/app/v1/auth/session"])
        let sessionToken = try await harness.credentials.read(.sessionToken)
        let installationToken = try await harness.credentials.read(.installationToken)
        XCTAssertEqual(sessionToken, "session")
        XCTAssertNotEqual(installationToken, old)
        XCTAssertEqual(harness.environment.account?.id, "account")
        XCTAssertTrue(harness.environment.premium)
        XCTAssertTrue(harness.environment.settings.accountDeletionUncertain)
    }

    func testSignOutRevokesSessionBeforeRecoveringLostRotation() async throws {
        let harness = try await environmentHarness(.signOutRotationConflict)
        defer { harness.session.invalidateAndCancel() }
        let old = "ic_install_" + String(repeating: "r", count: 43)
        try await harness.credentials.write(old, for: .installationToken)
        try await harness.credentials.write("session", for: .sessionToken)
        harness.environment.account = .init(displayName: "Person", email: "person@example.com", id: "account")
        harness.environment.settings.accountDeletionUncertain = true

        try await harness.environment.signOut()

        let requests = StubURLProtocol.requests()
        XCTAssertEqual(requests.map { $0.url?.path }, ["/api/installations/rotate", "/_allauth/app/v1/auth/session", "/api/installations"])
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "X-Session-Token"), "session")
        let sessionToken = try await harness.credentials.read(.sessionToken)
        let installationToken = try await harness.credentials.read(.installationToken)
        XCTAssertNil(sessionToken)
        XCTAssertNotEqual(installationToken, old)
        XCTAssertNil(harness.environment.account)
        XCTAssertFalse(harness.environment.settings.accountDeletionUncertain)
    }

    func testPrivacyManifestDeclaresNoTracking() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appending(path: "IlliniCover/Resources/PrivacyInfo.xcprivacy"))
        let manifest = try XCTUnwrap(PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any])
        XCTAssertEqual(manifest["NSPrivacyTracking"] as? Bool, false)
        XCTAssertTrue((manifest["NSPrivacyTrackingDomains"] as? [String] ?? []).isEmpty)
    }

    private static func report(id: String, venueID: String, observedAt: Date = .now) -> CoverSubmissionRequest {
        .init(clientPlatform: "ios", cover: .init(
            interaction: .direct, priceCents: 500, pricePrefilled: false, priceTouched: true,
            displayedSource: nil, displayedPriceKind: nil, displayedAmountCents: nil,
            displayedLowCents: nil, displayedHighCents: nil
        ), entryPoint: "test", location: nil, observedAt: observedAt, submissionId: id,
               vantagePoint: .unknown, venueId: venueID, vibes: [])
    }

    private static func suggestion(timing: String?, whileSuppliesLast: Bool) -> DealSuggestion {
        .init(canonicalFamilyId: "family", category: "drink", discountPercent: nil, displayName: "Deal",
              lastSeenServiceDateLocal: "2026-08-30", priceCents: 500, priceHighCents: nil,
              priceKind: "absolute", priceLowCents: nil, servingFormat: "can", sourceScope: "venue",
              timingDescription: timing, timingKnown: timing != nil || whileSuppliesLast, unit: "12 oz",
              whileSuppliesLast: whileSuppliesLast)
    }

    private typealias EnvironmentHarness = (environment: AppEnvironment, credentials: CredentialStore, database: AppDatabase, session: URLSession, defaults: UserDefaults)

    private func environmentHarness(_ scenario: StubURLProtocol.Scenario) async throws -> EnvironmentHarness {
        StubURLProtocol.reset(scenario)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let credentials = CredentialStore(service: "com.illinicover.environment-tests.\(UUID())")
        let database = try AppDatabase.temporary()
        let config = try AppConfiguration.validated([
            "ICAPIBaseURL": "http://127.0.0.1:8000", "ICEnvironment": "local",
        ], bundle: AppConfiguration.developmentBundle)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "com.illinicover.environment-defaults.\(UUID())"))
        return (AppEnvironment(api: LiveAPIClient(baseURL: config.apiBaseURL, credentials: credentials, session: session),
                               database: database, credentials: credentials, settings: AppSettings(defaults: defaults), configuration: config),
                credentials, database, session, defaults)
    }

    private func deletionHarness(_ scenario: StubURLProtocol.Scenario) async throws -> EnvironmentHarness {
        let harness = try await environmentHarness(scenario)
        try await harness.credentials.write("session", for: .sessionToken)
        try await harness.database.cache(Venue(id: "venue", slug: "venue", name: "Venue", address: "", openedYear: nil), key: "cache")
        harness.environment.account = .init(displayName: "Person", email: "person@example.com", id: "account")
        try await harness.credentials.write("ic_install_" + String(repeating: "d", count: 43), for: .installationToken)
        return harness
    }

    private func assertDeletionPurged(_ harness: EnvironmentHarness) async throws {
        let sessionToken = try await harness.credentials.read(.sessionToken)
        let installationToken = try await harness.credentials.read(.installationToken)
        let cached = try await harness.database.cached(Venue.self, key: "cache")
        XCTAssertNil(sessionToken)
        XCTAssertNotNil(installationToken)
        XCTAssertNil(harness.environment.account)
        XCTAssertFalse(harness.environment.settings.accountDeletionUncertain)
        XCTAssertNil(cached)
    }
}

private final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    enum Scenario {
        case installationRecovery, authRotation, authLinkRecovery, accountSwitch, outboxDrain
        case signOut, signOutRevocationAmbiguous, signOutRotationConflict
        case deleteUnauthorized, deleteAmbiguous, deleteSuccess, bootstrapDeleted, bootstrapAccountSurvives
    }
    private static let storage = Storage()

    static func reset(_ scenario: Scenario) { storage.reset(scenario) }
    static func requests() -> [URLRequest] { storage.requests() }
    static func bodies() -> [Data?] { storage.bodies() }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}
    override func startLoading() {
        let body = request.httpBody ?? request.httpBodyStream.flatMap(Self.read)
        let (status, data) = Self.storage.response(for: request, body: body)
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    private static func read(_ stream: InputStream) -> Data {
        stream.open(); defer { stream.close() }
        var data = Data(), buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            data.append(contentsOf: buffer.prefix(count))
        }
        return data
    }

    private final class Storage: @unchecked Sendable {
        private let lock = NSLock()
        private var captured: [URLRequest] = []
        private var capturedBodies: [Data?] = []
        private var submissions = 0
        private var confirmations = 0
        private var deletions = 0
        private var links = 0
        private var rotations = 0
        private var meRequests = 0
        private var scenario = Scenario.installationRecovery

        func reset(_ scenario: Scenario) { lock.withLock { self.scenario = scenario; captured = []; capturedBodies = []; submissions = 0; confirmations = 0; deletions = 0; links = 0; rotations = 0; meRequests = 0 } }
        func requests() -> [URLRequest] { lock.withLock { captured } }
        func bodies() -> [Data?] { lock.withLock { capturedBodies } }
        func response(for request: URLRequest, body: Data?) -> (Int, Data) {
            lock.withLock {
                captured.append(request)
                capturedBodies.append(body)
                let path = request.url?.path
                switch scenario {
                case .installationRecovery:
                    if path == "/api/cover-submissions" {
                        submissions += 1
                        if submissions == 1 { return (401, Data(#"{"message":"unauthorized"}"#.utf8)) }
                    }
                    return (201, Data("{}".utf8))
                case .authRotation:
                    if path == "/_allauth/app/v1/auth/code/resend" {
                        return (200, Data(#"{"meta":{"session_token":"challenge-2"}}"#.utf8))
                    }
                    confirmations += 1
                    if confirmations == 1 {
                        return (400, Data(#"{"meta":{"session_token":"challenge-3"}}"#.utf8))
                    }
                    return (200, Data(#"{"meta":{"is_authenticated":true,"session_token":"session-4"},"data":{"user":{"id":"account","email":"person@example.com","display":"Person"}}}"#.utf8))
                case .authLinkRecovery:
                    if path == "/_allauth/app/v1/auth/code/confirm" {
                        return (200, Data(#"{"meta":{"is_authenticated":true,"session_token":"session"},"data":{"user":{"id":"account","email":"person@example.com","display":"Person"}}}"#.utf8))
                    }
                    if path == "/api/me/link-installation" { links += 1; return links == 1 ? (503, Data()) : (204, Data()) }
                    if path == "/api/me" { return (200, Data(#"{"displayName":"Person","email":"person@example.com","id":"account"}"#.utf8)) }
                    return (200, Data(#"{"entitlements":[]}"#.utf8))
                case .accountSwitch:
                    if path == "/api/me" {
                        meRequests += 1
                        return meRequests == 1 ? (401, Data()) : (200, Data(#"{"displayName":"B","email":"b@example.com","id":"account-b"}"#.utf8))
                    }
                    if path == "/_allauth/app/v1/auth/code/confirm" {
                        return (200, Data(#"{"meta":{"is_authenticated":true,"session_token":"session-b"},"data":{"user":{"id":"account-b","email":"b@example.com","display":"B"}}}"#.utf8))
                    }
                    if path == "/api/me/link-installation" { links += 1; return links < 3 ? (409, Data()) : (200, Data("{}".utf8)) }
                    if path == "/api/installations/rotate" { rotations += 1; return rotations == 1 ? (503, Data()) : (201, Data("{}".utf8)) }
                    return (200, Data(#"{"entitlements":[]}"#.utf8))
                case .outboxDrain:
                    return (201, Data("{}".utf8))
                case .signOut:
                    if path == "/_allauth/app/v1/auth/session" { return (401, Data(#"{"message":"expired"}"#.utf8)) }
                    return (201, Data("{}".utf8))
                case .signOutRevocationAmbiguous:
                    return path == "/_allauth/app/v1/auth/session" ? (503, Data()) : (201, Data("{}".utf8))
                case .signOutRotationConflict:
                    if path == "/api/installations/rotate" { return (422, Data()) }
                    return path == "/_allauth/app/v1/auth/session" ? (204, Data()) : (201, Data("{}".utf8))
                case .deleteUnauthorized:
                    return (401, Data(#"{"message":"expired"}"#.utf8))
                case .deleteAmbiguous:
                    if path == "/api/me" { deletions += 1; return deletions == 1 ? (503, Data(#"{"message":"uncertain"}"#.utf8)) : (401, Data()) }
                    return (201, Data("{}".utf8))
                case .deleteSuccess:
                    return path == "/api/me" ? (204, Data()) : (201, Data("{}".utf8))
                case .bootstrapDeleted:
                    return path == "/api/me" ? (401, Data()) : (201, Data("{}".utf8))
                case .bootstrapAccountSurvives:
                    if path == "/api/me" { return (200, Data(#"{"displayName":"Person","email":"person@example.com","id":"account"}"#.utf8)) }
                    return (200, Data(#"{"entitlements":[]}"#.utf8))
                }
            }
        }
    }
}
