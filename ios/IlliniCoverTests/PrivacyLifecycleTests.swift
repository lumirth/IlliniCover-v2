import Foundation
import Security
import Testing
@testable import IlliniCover

@Suite("Privacy lifecycle", .serialized)
@MainActor
struct PrivacyLifecycleTests {
    @Test("Acceptance reset stays gated when required Keychain erasure fails")
    @MainActor
    func acceptanceResetKeychainFailureStaysFailClosed() async throws {
        let database = try AppDatabase.temporary()
        try await database.cache(CoverBoardResponse.fixture, key: "cover-board", etag: "private-cache")
        let service = "com.illinicover.tests.acceptance-reset-keychain.\(UUID().uuidString)"
        let seedCredentials = CredentialStore(service: service)
        try await seedCredentials.writeRequired("session-secret", for: .sessionToken)
        let failingCredentials = CredentialStore(service: service) { operation, key in
            operation == .delete && key == .sessionToken ? errSecInteractionNotAllowed : nil
        }
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = AppEnvironment(
            api: PreviewAPIClient(),
            database: database,
            credentials: failingCredentials,
            settings: AppSettings(defaults: defaults),
            configuration: AppConfiguration(
                apiBaseURL: URL(string: "https://example.invalid")!,
                revenueCatAPIKey: nil
            ),
            acceptanceResetPending: true
        )

        await environment.bootstrap()

        #expect(environment.acceptanceResetPending)
        #expect(environment.globalNotice == "Acceptance-state reset failed. Product data stays hidden.")
        #expect(try await database.cached(CoverBoardResponse.self, key: "cover-board") == nil)
        #expect(try await seedCredentials.readRequired(.sessionToken) == "session-secret")

        try await seedCredentials.deleteAllRequired()
    }

    private enum PurgeFailure: Error { case expected }

    @Test("Deleting an account purges private cache, queued location, and credentials")
    func deletionPurgesAllLocalIdentityState() async throws {
        let database = try AppDatabase.temporary()
        let service = "com.illinicover.tests.delete.\(UUID().uuidString)"
        let credentials = CredentialStore(service: service)
        await credentials.write("session", for: .sessionToken)
        await credentials.write("installation", for: .installationToken)
        let request = CoverSubmissionRequest(
            submissionId: "must-never-send",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 321),
            vantagePoint: .outside,
            location: .init(latitude: 40.11, longitude: -88.23, accuracyMeters: 5),
            cover: CoverObservationRequest(priceCents: 1_000, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        try await database.cache(EntitlementSummary(premium: true, expiresAt: nil), key: "account-private", etag: nil)
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = AppEnvironment(
            api: PreviewAPIClient(),
            database: database,
            credentials: credentials,
            settings: AppSettings(defaults: defaults),
            configuration: AppConfiguration(apiBaseURL: URL(string: "https://example.invalid")!, revenueCatAPIKey: nil)
        )
        try await environment.didAuthenticate(
            AccountSummary(id: "account", email: "test@example.com", firstName: "Test", graduationYear: nil)
        )

        try await environment.deleteAccount()

        #expect(environment.account == nil)
        #expect(environment.premium == false)
        #expect(environment.outboxStatus == .empty)
        #expect(try await database.outboxCount() == 0)
        #expect(try await database.cached(EntitlementSummary.self, key: "account-private") == nil)
        let deletedSession = await credentials.read(.sessionToken)
        let replacementInstallation = await credentials.read(.installationToken)
        #expect(deletedSession == nil)
        #expect(replacementInstallation?.hasPrefix("ic_install_") == true)
        #expect(environment.billing.deletedIdentityWasRetired)
        #expect(await credentials.read(.linkedAccountID) == nil)
        await credentials.deleteAll()
    }

    @Test("Guest identity never rotates when the required local purge fails")
    func failedPurgePreventsGuestUnlink() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let database = try AppDatabase(
            path: directory.appending(path: "purge-failure.sqlite").path,
            resetPreflight: { throw PurgeFailure.expected }
        )
        let request = CoverSubmissionRequest(
            submissionId: "old-location",
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside,
            location: .init(latitude: 40.11, longitude: -88.23, accuracyMeters: 5),
            cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let api = PreviewAPIClient()
        let credentials = CredentialStore(service: "com.illinicover.tests.rotate.\(UUID().uuidString)")
        await credentials.write("guest-installation", for: .installationToken)
        let environment = AppEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            settings: AppSettings(defaults: defaults),
            configuration: AppConfiguration(apiBaseURL: URL(string: "https://example.invalid")!, revenueCatAPIKey: nil)
        )

        await #expect(throws: PurgeFailure.self) { try await environment.rotateGuestActor() }

        #expect(await api.rotationCount == 0)
        #expect(environment.settings.privacyPurgePending)
        #expect(try await database.outboxCount() == 1)
    }

    @Test("An uncommitted account-deletion transport error retains retry authority")
    func deletionTransportFailureRetainsRequestAndSession() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.delete-loss.\(UUID().uuidString)")
        await credentials.write("session", for: .sessionToken)
        await credentials.write("installation", for: .installationToken)
        try await enqueueLocationObservation(in: database, id: "delete-loss-location")
        let api = PreviewAPIClient(deleteAccountBehavior: {
            throw APIClientError.transport("response_lost")
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await seedAccount(api: api, environment: environment)

        await #expect(throws: APIClientError.self) { try await environment.deleteAccount() }

        #expect(try await database.outboxCount() == 0)
        let retainedSession = await credentials.read(.sessionToken)
        let retainedInstallation = await credentials.read(.installationToken)
        #expect(retainedSession == "session")
        #expect(retainedInstallation == "installation")
        #expect(environment.settings.pendingPrivacyTransition == .deleteAccount)
        #expect(UUID(uuidString: try #require(environment.settings.pendingPrivacyRequestID)) != nil)
        #expect(await api.deletionCount == 1)
        #expect(await api.installationCount == 0)
    }

    @Test("A Keychain deletion failure keeps account deletion pending")
    func keychainFailureCannotFalselyCompleteDeletion() async throws {
        let database = try AppDatabase.temporary()
        let service = "com.illinicover.tests.delete-keychain-failure.\(UUID().uuidString)"
        let seedCredentials = CredentialStore(service: service)
        try await seedCredentials.writeRequired("session", for: .sessionToken)
        try await seedCredentials.writeRequired("installation", for: .installationToken)
        let failingCredentials = CredentialStore(service: service) { operation, key in
            operation == .delete && key == .sessionToken ? errSecInteractionNotAllowed : nil
        }
        try await enqueueLocationObservation(in: database, id: "delete-keychain-location")
        let api = PreviewAPIClient()
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(
            api: api,
            database: database,
            credentials: failingCredentials,
            defaults: defaults
        )
        await seedAccount(api: api, environment: environment)

        await #expect(throws: CredentialStoreError.self) {
            try await environment.deleteAccount()
        }

        #expect(environment.settings.pendingPrivacyTransition == .deleteAccount)
        #expect(environment.settings.pendingPrivacyRequestID != nil)
        #expect(await api.deletionCount == 1)
        #expect(try await database.outboxCount() == 0)
        #expect(try await seedCredentials.readRequired(.sessionToken) == "session")
        #expect(try await seedCredentials.readRequired(.installationToken) == "installation")
        #expect(!environment.billing.deletedIdentityWasRetired)

        await seedCredentials.deleteAll()
    }

    @Test("A committed deletion with a lost response is confirmed by receipt on relaunch")
    func deletionResponseLossConfirmsOnRelaunch() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.delete-committed.\(UUID().uuidString)")
        await credentials.write("session", for: .sessionToken)
        await credentials.write("installation", for: .installationToken)
        try await enqueueLocationObservation(in: database, id: "delete-committed-location")
        let attempts = AttemptCounter()
        let completed = DeletionReceiptStore()
        let api = PreviewAPIClient(
            deleteAccountBehavior: {
                if await attempts.take() == 1 { throw APIClientError.transport("response_lost") }
            },
            deletionStatusBehavior: { requestID in await completed.contains(requestID) }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await seedAccount(api: api, environment: environment)

        await #expect(throws: APIClientError.self) { try await environment.deleteAccount() }
        let requestID = try #require(environment.settings.pendingPrivacyRequestID)
        await completed.insert(requestID)

        let relaunched = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await relaunched.bootstrap()

        #expect(relaunched.settings.pendingPrivacyTransition == .none)
        #expect(relaunched.settings.pendingPrivacyRequestID == nil)
        let deletedSession = await credentials.read(.sessionToken)
        let replacementInstallation = await credentials.read(.installationToken)
        #expect(deletedSession == nil)
        #expect(replacementInstallation?.hasPrefix("ic_install_") == true)
        #expect(try await database.outboxCount() == 0)
    }

    @Test("Pending account deletion cannot become guest rotation and recovers in foreground")
    func pendingDeletionCannotBeOverwritten() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.delete-foreground.\(UUID().uuidString)")
        await credentials.write("session", for: .sessionToken)
        await credentials.write("installation", for: .installationToken)
        let completed = DeletionReceiptStore()
        let api = PreviewAPIClient(
            deleteAccountBehavior: { throw APIClientError.transport("offline") },
            deletionStatusBehavior: { requestID in await completed.contains(requestID) }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await seedAccount(api: api, environment: environment)
        await environment.bootstrap()

        await #expect(throws: APIClientError.self) { try await environment.deleteAccount() }
        let deletionRequestID = try #require(environment.settings.pendingPrivacyRequestID)

        await #expect(throws: APIClientError.self) { try await environment.rotateGuestActor() }
        #expect(environment.settings.pendingPrivacyTransition == .deleteAccount)
        #expect(environment.settings.pendingPrivacyRequestID == deletionRequestID)
        #expect(await api.rotationCount == 0)

        await completed.insert(deletionRequestID)
        await environment.didEnterForeground()

        #expect(environment.settings.pendingPrivacyTransition == .none)
        #expect(environment.settings.pendingPrivacyRequestID == nil)
        #expect(await credentials.read(.sessionToken) == nil)
        #expect(await credentials.read(.installationToken)?.hasPrefix("ic_install_") == true)
    }

    @Test("An expired deletion session can be restored only by the original account")
    func expiredDeletionSessionCanReauthenticateOriginalAccount() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.delete-reauth.\(UUID().uuidString)")
        await credentials.write("expired-session", for: .sessionToken)
        await credentials.write("installation", for: .installationToken)
        let authorization = AvailabilityGate()
        let api = PreviewAPIClient(deleteAccountBehavior: {
            guard await authorization.isAvailable else { throw APIClientError.unauthorized }
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        let original = await seedAccount(api: api, environment: environment)
        await environment.bootstrap()

        await #expect(throws: APIClientError.self) { try await environment.deleteAccount() }
        #expect(environment.hasPendingAccountDeletion)
        await credentials.delete(.sessionToken)
        await environment.didEnterForeground()
        #expect(environment.hasPendingAccountDeletion)

        await #expect(throws: APIClientError.self) {
            try await environment.didAuthenticate(
                AccountSummary(id: "different-account", email: "other@example.com", firstName: nil, graduationYear: nil)
            )
        }
        #expect(environment.hasPendingAccountDeletion)

        await authorization.restore()
        await credentials.write("fresh-session", for: .sessionToken)
        try await environment.didAuthenticate(original)

        #expect(!environment.hasPendingAccountDeletion)
        #expect(await credentials.read(.pendingDeletionAccountID) == nil)
        #expect(await credentials.read(.sessionToken) == nil)
        #expect(await credentials.read(.installationToken)?.hasPrefix("ic_install_") == true)
    }

    @Test("Foreground connectivity recovery issues installation before draining queued reports")
    func installationIssuanceRecoversBeforeOutboxDrain() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.install-recovery.\(UUID().uuidString)")
        let availability = AvailabilityGate()
        let api = PreviewAPIClient(createInstallationBehavior: {
            guard await availability.isAvailable else { throw APIClientError.transport("offline") }
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await environment.bootstrap()

        let request = CoverSubmissionRequest(
            submissionId: "first-use-offline", venueId: "venue", observedAt: Date(timeIntervalSince1970: 123),
            vantagePoint: .outside, location: nil,
            cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await environment.outbox.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
        await Task.yield()
        #expect(try await database.outboxCount() == 1)
        #expect(await credentials.read(.installationToken) == nil)

        await availability.restore()
        await environment.didEnterForeground()

        #expect(await credentials.read(.installationToken)?.hasPrefix("ic_install_") == true)
        #expect(try await database.outboxCount() == 0)
    }

    @Test("Deletion on another device signs out billing, purges old evidence, and reissues the revoked actor")
    func remoteAccountDeletionRecoversLiveDevice() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.remote-delete.\(UUID().uuidString)")
        let api = PreviewAPIClient(
            accountBehavior: { throw APIClientError.unauthorized },
            outboxBehavior: { _, _ in throw APIClientError.unauthorized }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await environment.bootstrap()
        let oldAccount = AccountSummary(id: "deleted-elsewhere", email: "deleted@example.com", firstName: "Deleted", graduationYear: nil)
        environment.account = oldAccount
        environment.premium = true
        await credentials.write("revoked-session", for: .sessionToken)
        await credentials.write("revoked-installation", for: .installationToken)
        await credentials.write(oldAccount.id, for: .linkedAccountID)
        try await enqueueLocationObservation(in: database, id: "must-not-return-after-remote-delete")

        await environment.didEnterForeground()

        #expect(environment.account == nil)
        #expect(!environment.premium)
        #expect(!environment.billing.isConfigured)
        #expect(environment.billing.currentAccountID == nil)
        #expect(await credentials.read(.sessionToken) == nil)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "revoked-installation")
        #expect(await api.installationCount >= 2)
        #expect(try await database.outboxCount() == 0)
        #expect(await api.outboxCount == 1)
        #expect(environment.billing.deletedIdentityWasRetired)
        #expect(await credentials.read(.linkedAccountID) == nil)
        #expect(environment.globalNotice?.contains("no longer active") == true)
        #expect(environment.globalNotice?.contains("were not resent") == true)
    }

    @Test("Foreground probe honors remote account deletion even with an empty outbox")
    func remoteAccountDeletionWithoutQueuedReportStillPurgesPrivateState() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.remote-delete-empty.\(UUID().uuidString)")
        await credentials.write("expired-session", for: .sessionToken)
        await credentials.write("revoked-installation", for: .installationToken)
        await credentials.write("deleted-account", for: .linkedAccountID)
        try await database.cache(
            EntitlementSummary(premium: true, expiresAt: nil),
            key: "private-account-cache",
            etag: nil
        )
        let probeAttempts = AttemptCounter()
        let api = PreviewAPIClient(
            currentInstallationBehavior: {
                if await probeAttempts.take() == 1 { throw APIClientError.unauthorized }
            },
            accountBehavior: { throw APIClientError.unauthorized }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        environment.account = AccountSummary(
            id: "deleted-account",
            email: "deleted@example.com",
            firstName: nil,
            graduationYear: nil
        )
        environment.premium = true

        await environment.bootstrap()
        await environment.didEnterForeground()

        #expect(await api.accountReadCount == 1)
        // Bootstrap proves the revoked actor and foreground validates the
        // freshly issued replacement without mutating either identity.
        #expect(await api.installationReadCount == 2)
        #expect(await api.outboxCount == 0)
        #expect(environment.account == nil)
        #expect(!environment.premium)
        #expect(environment.billing.deletedIdentityWasRetired)
        #expect(try await database.cached(EntitlementSummary.self, key: "private-account-cache") == nil)
        #expect(try await database.outboxCount() == 0)
        #expect(await credentials.read(.linkedAccountID) == nil)
        #expect(await credentials.read(.sessionToken) == nil)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "revoked-installation")
        #expect(await api.installationCount == 1)
        #expect(environment.globalNotice?.contains("no longer active") == true)
    }

    @Test("A pending email challenge never masquerades as an authenticated session")
    func pendingChallengeSurvivesRelaunchWithoutPrivatePurge() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.pending-code.\(UUID().uuidString)")
        await credentials.write("installation", for: .installationToken)
        await credentials.write("pending-allauth-token", for: .emailChallengeToken)
        try await enqueueLocationObservation(in: database, id: "pending-code-location")
        let api = PreviewAPIClient(
            accountBehavior: { throw APIClientError.unauthorized },
            outboxBehavior: { _, _ in throw APIClientError.transport("offline") }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await environment.bootstrap()

        #expect(await api.accountReadCount == 0)
        #expect(await credentials.read(.sessionToken) == nil)
        #expect(await credentials.read(.emailChallengeToken) == "pending-allauth-token")
        #expect(try await database.outboxCount() == 1)
        #expect(!environment.billing.deletedIdentityWasRetired)
    }

    @Test("An expired account session disables billing without erasing a still-valid linked actor")
    func expiredSessionPreservesEvidenceUntilActorValidation() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.expired-session.\(UUID().uuidString)")
        await credentials.write("expired-session", for: .sessionToken)
        await credentials.write("still-valid-installation", for: .installationToken)
        await credentials.write("account-a", for: .linkedAccountID)
        try await enqueueLocationObservation(in: database, id: "expired-session-location")
        let api = PreviewAPIClient(accountBehavior: { throw APIClientError.unauthorized })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        environment.account = AccountSummary(id: "account-a", email: "a@example.com", firstName: nil, graduationYear: nil)
        environment.premium = true

        await environment.bootstrap()
        await environment.didEnterForeground()

        #expect(environment.account == nil)
        #expect(!environment.premium)
        #expect(!environment.billing.isConfigured)
        #expect(!environment.billing.deletedIdentityWasRetired)
        #expect(await credentials.read(.sessionToken) == nil)
        #expect(await credentials.read(.linkedAccountID) == "account-a")
        #expect(await api.outboxCount == 1)
        #expect(try await database.outboxCount() == 0)
        #expect(environment.globalNotice?.contains("session ended") == true)
    }

    @Test("Signing out ends attribution while retaining the durable privacy-ownership link")
    func signOutPreservesDurableActorLink() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.signed-out-link.\(UUID().uuidString)")
        let api = PreviewAPIClient()
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await environment.bootstrap()
        let response = try await api.verifyEmailCode(code: "BCDF-GHJK", intent: .signIn)
        try await environment.didAuthenticate(response.account)

        try await environment.signOut()

        #expect(environment.account == nil)
        #expect(!environment.premium)
        #expect(environment.installationMayRemainAccountLinked)
        #expect(await credentials.read(.linkedAccountID) == response.account.id)
        #expect(await credentials.read(.sessionToken) == nil)
    }

    @Test("Signing out after a lost link response preserves the erasure boundary across relaunch")
    func signOutPreservesPendingLinkReceiptUntilActorValidation() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.signed-out-pending-link.\(UUID().uuidString)")
        try await credentials.writeRequired("revoked-installation", for: .installationToken)
        try await credentials.writeRequired("session", for: .sessionToken)
        try await database.cache(
            EntitlementSummary(premium: true, expiresAt: nil),
            key: "possibly-linked-private-cache",
            etag: nil
        )
        let api = PreviewAPIClient(
            currentInstallationBehavior: { throw APIClientError.unauthorized },
            linkInstallationBehavior: { throw APIClientError.transport("response_lost") }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            defaults: defaults
        )

        await #expect(throws: APIClientError.self) {
            try await environment.didAuthenticate(
                AccountSummary(id: "possibly-linked-account", email: "link@example.com", firstName: nil, graduationYear: nil)
            )
        }
        let requestID = try #require(environment.settings.pendingLinkRequestID)

        try await environment.signOut()

        #expect(environment.settings.pendingLinkRequestID == requestID)
        #expect(environment.installationMayRemainAccountLinked)
        #expect(await credentials.read(.sessionToken) == nil)

        let relaunched = makeEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            defaults: defaults
        )
        await relaunched.bootstrap()

        #expect(relaunched.settings.pendingLinkRequestID == nil)
        #expect(!relaunched.installationMayRemainAccountLinked)
        #expect(relaunched.billing.deletedIdentityWasRetired)
        #expect(try await database.cached(EntitlementSummary.self, key: "possibly-linked-private-cache") == nil)
        #expect(relaunched.globalNotice?.contains("no longer active") == true)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "revoked-installation")
    }

    @Test("A lost link response is an account-erasure boundary when the installation is revoked")
    func pendingLinkReceiptPurgesInsteadOfRetryingAsGuest() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.pending-link-revoked.\(UUID().uuidString)")
        try await credentials.writeRequired("revoked-installation", for: .installationToken)
        try await database.cache(
            EntitlementSummary(premium: true, expiresAt: nil),
            key: "possibly-linked-private-cache",
            etag: nil
        )
        let attempts = AttemptCounter()
        let api = PreviewAPIClient(currentInstallationBehavior: {
            if await attempts.take() == 1 { throw APIClientError.unauthorized }
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let settings = AppSettings(defaults: defaults)
        settings.pendingLinkRequestID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        let environment = AppEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            settings: settings,
            configuration: AppConfiguration(apiBaseURL: URL(string: "https://example.invalid")!, revenueCatAPIKey: nil)
        )

        await environment.bootstrap()

        #expect(settings.pendingLinkRequestID == nil)
        #expect(!environment.installationMayRemainAccountLinked)
        #expect(environment.billing.deletedIdentityWasRetired)
        #expect(try await database.cached(EntitlementSummary.self, key: "possibly-linked-private-cache") == nil)
        #expect(environment.globalNotice?.contains("no longer active") == true)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "revoked-installation")
    }

    @Test("An ordinary revoked guest actor keeps and retries its exact queued request")
    func revokedGuestInstallationRetriesAfterReissue() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.revoked-guest.\(UUID().uuidString)")
        await credentials.write("revoked-guest-installation", for: .installationToken)
        let attempts = AttemptCounter()
        let api = PreviewAPIClient(outboxBehavior: { _, _ in
            if await attempts.take() == 1 { throw APIClientError.unauthorized }
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await environment.bootstrap()
        try await enqueueLocationObservation(in: database, id: "guest-retry-same-payload")

        await environment.outbox.drain()

        #expect(environment.account == nil)
        #expect(await credentials.read(.sessionToken) == nil)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "revoked-guest-installation")
        #expect(await api.installationCount == 1)
        #expect(await api.outboxCount == 2)
        #expect(try await database.outboxCount() == 0)
    }

    @Test("A committed rotation with a lost response recovers after relaunch without old payloads")
    func rotationResponseLossRecoversOnBootstrap() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.rotate-loss.\(UUID().uuidString)")
        await credentials.write("old-now-invalid", for: .installationToken)
        try await enqueueLocationObservation(in: database, id: "rotation-loss-location")
        let attempts = AttemptCounter()
        let receipt = RotationReceiptStore()
        let api = PreviewAPIClient(tokenOperationBehavior: { requestID, replacement, authorization in
            guard authorization != nil else { return }
            if await attempts.take() == 1 {
                await receipt.record(requestID: requestID, replacement: replacement)
                throw APIClientError.transport("response_lost")
            }
            guard await receipt.matches(requestID: requestID, replacement: replacement) else {
                throw APIClientError.server(APIErrorPayload(code: "idempotency_conflict", message: "conflict", requestId: requestID), status: 409)
            }
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await #expect(throws: APIClientError.self) { try await environment.rotateGuestActor() }
        #expect(environment.settings.pendingPrivacyTransition == .rotateGuest)
        #expect(try await database.outboxCount() == 0)

        let relaunched = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await relaunched.bootstrap()

        #expect(relaunched.settings.pendingPrivacyTransition == .none)
        let replacementInstallation = await credentials.read(.installationToken)
        #expect(replacementInstallation?.hasPrefix("ic_install_") == true)
        #expect(try await database.outboxCount() == 0)
        #expect(await api.rotationCount == 2)
        #expect(await api.installationCount == 0)
    }

    @Test("An installation linked to another account blocks authenticated and billing state")
    func accountSwitchConflictIsNotHidden() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.link-conflict.\(UUID().uuidString)")
        await credentials.write("session-b", for: .sessionToken)
        await credentials.write("actor-a", for: .installationToken)
        let api = PreviewAPIClient(linkInstallationBehavior: {
            throw APIClientError.server(
                APIErrorPayload(code: "installation_already_linked", message: "linked", requestId: "request"),
                status: 409
            )
        })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let environment = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await #expect(throws: APIClientError.self) {
            try await environment.didAuthenticate(
                AccountSummary(id: "account-b", email: "b@example.com", firstName: "B", graduationYear: nil)
            )
        }

        #expect(environment.account == nil)
        #expect(environment.billing.currentAccountID == nil)
        #expect(!environment.billing.isConfigured)
        let deletedSession = await credentials.read(.sessionToken)
        let retainedInstallation = await credentials.read(.installationToken)
        let conflictMarker = await credentials.read(.accountLinkConflict)
        #expect(deletedSession == nil)
        #expect(retainedInstallation == "actor-a")
        #expect(conflictMarker == "linked-elsewhere")
        #expect(environment.settings.pendingLinkRequestID == nil)
        #expect(environment.installationMayRemainAccountLinked)
        #expect(await api.linkCount == 1)
    }

    @Test("A link conflict remains an erasure boundary across relaunch and revoked actor recovery")
    func accountSwitchConflictPurgesBeforeGuestRecoveryAfterRelaunch() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.link-conflict-relaunch.\(UUID().uuidString)")
        try await credentials.writeRequired("session-b", for: .sessionToken)
        try await credentials.writeRequired("actor-linked-elsewhere", for: .installationToken)
        let api = PreviewAPIClient(
            currentInstallationBehavior: { throw APIClientError.unauthorized },
            linkInstallationBehavior: {
                throw APIClientError.server(
                    APIErrorPayload(code: "installation_already_linked", message: "linked", requestId: "request"),
                    status: 409
                )
            }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let firstLaunch = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await #expect(throws: APIClientError.self) {
            try await firstLaunch.didAuthenticate(
                AccountSummary(id: "account-b", email: "b@example.com", firstName: "B", graduationYear: nil)
            )
        }
        #expect(await credentials.read(.accountLinkConflict) == "linked-elsewhere")
        try await database.cache(
            EntitlementSummary(premium: true, expiresAt: nil),
            key: "linked-elsewhere-private-cache",
            etag: nil
        )
        try await enqueueLocationObservation(in: database, id: "linked-elsewhere-location")

        let relaunched = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await relaunched.bootstrap()

        #expect(!relaunched.installationMayRemainAccountLinked)
        #expect(relaunched.billing.deletedIdentityWasRetired)
        #expect(relaunched.globalNotice?.contains("no longer active") == true)
        #expect(try await database.cached(EntitlementSummary.self, key: "linked-elsewhere-private-cache") == nil)
        #expect(try await database.outboxCount() == 0)
        #expect(await api.outboxCount == 0)
        #expect(await credentials.read(.accountLinkConflict) == nil)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "actor-linked-elsewhere")
    }

    @Test("A valid actor owned by another account keeps reporting and delivery paused after relaunch")
    func accountSwitchConflictWithValidActorCannotSendAsTheOwningAccount() async throws {
        let database = try AppDatabase.temporary()
        let credentials = CredentialStore(service: "com.illinicover.tests.link-conflict-valid.\(UUID().uuidString)")
        try await credentials.writeRequired("session-b", for: .sessionToken)
        try await credentials.writeRequired("actor-a-still-valid", for: .installationToken)
        let coverAttempts = AttemptCounter()
        let api = PreviewAPIClient(
            linkInstallationBehavior: {
                throw APIClientError.server(
                    APIErrorPayload(code: "installation_already_linked", message: "linked", requestId: "request"),
                    status: 409
                )
            },
            coverSubmissionBehavior: { _ in _ = await coverAttempts.take() }
        )
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let firstLaunch = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await #expect(throws: APIClientError.self) {
            try await firstLaunch.didAuthenticate(
                AccountSummary(id: "account-b", email: "b@example.com", firstName: "B", graduationYear: nil)
            )
        }
        try await enqueueLocationObservation(in: database, id: "must-not-send-as-account-a")

        let relaunched = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await relaunched.bootstrap()
        await relaunched.outbox.drain()
        let quickOutcome = await CoverBoardModel().quickSubmit(
            venue: CoverBoardResponse.fixture.venues[0].venue,
            decision: CoverBoardResponse.fixture.venues[0].cover,
            cents: 2_000,
            interaction: .quickConfirm,
            environment: relaunched
        )

        #expect(relaunched.hasAccountLinkConflict)
        #expect(!relaunched.canSubmitReports)
        #expect(relaunched.globalNotice == AppEnvironment.accountLinkConflictNotice)
        #expect(await credentials.read(.accountLinkConflict) == "linked-elsewhere")
        #expect(try await database.outboxCount() == 1)
        #expect(await api.outboxCount == 0)
        #expect(await coverAttempts.count() == 0)
        #expect(quickOutcome == .failed)
        #expect(await credentials.read(.installationToken) == "actor-a-still-valid")
    }

    @Test("A successful link keeps its pending ownership marker until Keychain persistence succeeds")
    func linkedAccountWriteFailureStillPurgesAfterRelaunchAndRevocation() async throws {
        let database = try AppDatabase.temporary()
        let service = "com.illinicover.tests.link-write-failure.\(UUID().uuidString)"
        let seedCredentials = CredentialStore(service: service)
        try await seedCredentials.writeRequired("session-a", for: .sessionToken)
        try await seedCredentials.writeRequired("actor-a", for: .installationToken)
        let credentials = CredentialStore(service: service) { operation, key in
            operation == .write && key == .linkedAccountID ? errSecInteractionNotAllowed : nil
        }
        let api = PreviewAPIClient(currentInstallationBehavior: { throw APIClientError.unauthorized })
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverTests.\(UUID().uuidString)"))
        let firstLaunch = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)

        await #expect(throws: CredentialStoreError.self) {
            try await firstLaunch.didAuthenticate(
                AccountSummary(id: "account-a", email: "a@example.com", firstName: "A", graduationYear: nil)
            )
        }
        let retainedRequestID = try #require(firstLaunch.settings.pendingLinkRequestID)
        try await database.cache(
            EntitlementSummary(premium: true, expiresAt: nil),
            key: "link-write-failure-private-cache",
            etag: nil
        )
        try await enqueueLocationObservation(in: database, id: "link-write-failure-location")

        let relaunched = makeEnvironment(api: api, database: database, credentials: credentials, defaults: defaults)
        await relaunched.bootstrap()

        #expect(retainedRequestID.isEmpty == false)
        #expect(relaunched.settings.pendingLinkRequestID == nil)
        #expect(!relaunched.installationMayRemainAccountLinked)
        #expect(relaunched.billing.deletedIdentityWasRetired)
        #expect(try await database.cached(EntitlementSummary.self, key: "link-write-failure-private-cache") == nil)
        #expect(try await database.outboxCount() == 0)
        #expect(await api.outboxCount == 0)
        let replacement = try #require(await credentials.read(.installationToken))
        #expect(replacement.hasPrefix("ic_install_"))
        #expect(replacement != "actor-a")
    }

    private func makeEnvironment(
        api: PreviewAPIClient,
        database: AppDatabase,
        credentials: CredentialStore,
        defaults: UserDefaults
    ) -> AppEnvironment {
        AppEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            settings: AppSettings(defaults: defaults),
            configuration: AppConfiguration(apiBaseURL: URL(string: "https://example.invalid")!, revenueCatAPIKey: nil)
        )
    }

    @discardableResult
    private func seedAccount(api: PreviewAPIClient, environment: AppEnvironment) async -> AccountSummary {
        let response = try! await api.verifyEmailCode(code: "BCDF-GHJK", intent: .signIn)
        environment.account = response.account
        return response.account
    }

    private func enqueueLocationObservation(in database: AppDatabase, id: String) async throws {
        let request = CoverSubmissionRequest(
            submissionId: id,
            venueId: "venue",
            observedAt: Date(timeIntervalSince1970: 777),
            vantagePoint: .outside,
            location: .init(latitude: 40.11, longitude: -88.23, accuracyMeters: 5),
            cover: CoverObservationRequest(priceCents: 500, interaction: .manual, displayedDecisionId: nil, pricePrefilled: false, priceTouched: true),
            vibes: []
        )
        try await database.enqueue(id: request.id, kind: .cover, observedAt: request.observedAt, value: request)
    }
}

private actor AttemptCounter {
    private var value = 0
    func take() -> Int { value += 1; return value }
    func count() -> Int { value }
}

private actor DeletionReceiptStore {
    private var completed = Set<String>()
    func insert(_ requestID: String) { completed.insert(requestID) }
    func contains(_ requestID: String) -> Bool { completed.contains(requestID) }
}

private actor RotationReceiptStore {
    private var value: (String, String)?
    func record(requestID: String, replacement: String) { value = (requestID, replacement) }
    func matches(requestID: String, replacement: String) -> Bool {
        value?.0 == requestID && value?.1 == replacement
    }
}

private actor AvailabilityGate {
    private var available = false
    var isAvailable: Bool { available }
    func restore() { available = true }
}
