import Foundation
import Observation
import OSLog

enum AppRuntimeMode: Equatable {
    case standard
    case uiTesting
    case liveAcceptance

    static func resolve(arguments: [String]) -> AppRuntimeMode {
#if DEBUG
        if arguments.contains("-uiTesting") { return .uiTesting }
        if arguments.contains("-liveAcceptance") { return .liveAcceptance }
#endif
        return .standard
    }

    static func permitsLiveAcceptanceBaseURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }
}

struct AppStorageIdentity: Equatable, Sendable {
    let credentialService: String
    let defaultsSuite: String
    let databaseNamespace: String

    static func resolve(
        bundleIdentifier: String,
        deploymentEnvironment: AppDeploymentEnvironment,
        runtimeMode: AppRuntimeMode
    ) -> Self {
        let suffix: String
        switch runtimeMode {
        case .uiTesting: suffix = "ui-testing"
        case .liveAcceptance: suffix = "live-acceptance"
        case .standard: suffix = deploymentEnvironment.rawValue
        }
        return Self(
            credentialService: "\(bundleIdentifier).credentials.\(suffix)",
            defaultsSuite: "\(bundleIdentifier).defaults.\(suffix)",
            databaseNamespace: suffix
        )
    }
}

@MainActor
@Observable
final class AppEnvironment {
    let api: any AppAPI
    let database: AppDatabase
    let credentials: CredentialStore
    let outbox: OutboxProcessor
    let settings: AppSettings
    let location: LocationClient
    let billing: BillingModel
    let configuration: AppConfiguration
    let runtimeMode: AppRuntimeMode

    var account: AccountSummary?
    var premium = false
    /// Signing out removes only the account session. The installation actor's
    /// durable link (including a link known to belong to another account, or
    /// an idempotent link whose response was lost) remains an account
    /// deletion/privacy boundary. Reports made while signed out are
    /// guest-attributed until the owning account reauthenticates.
    var installationMayRemainAccountLinked = false
    /// A 409 proves that this actor belongs to an account other than the one
    /// that just authenticated. That account's attribution remains active
    /// until its own authenticated logout or actor rotation, so this state
    /// blocks report creation and delivery rather than mislabeling it guest.
    var hasAccountLinkConflict = false
    var isBootstrapping = true
    var globalNotice: String?
    var outboxStatus = OutboxStatus.empty
    var failedSubmissions: [FailedSubmissionSummary] = []
    var acceptanceResetPending: Bool
    var pendingDeepLinkVenueID: String?

    var hasPendingAccountDeletion: Bool {
        settings.pendingPrivacyTransition == .deleteAccount
    }

    var canSubmitReports: Bool {
        settings.pendingPrivacyTransition == .none && !hasAccountLinkConflict
    }

    static let accountLinkConflictNotice = "Reporting is paused because this installation belongs to another account. Sign in to that account or delete and rotate this installation before reporting."

    private let logger = Logger(subsystem: "com.illinicover.app.v2", category: "app")
    private var bootstrapTask: Task<Void, Never>?
    private var installationIssuance: Task<Void, Error>?

    init(
        api: any AppAPI,
        database: AppDatabase,
        credentials: CredentialStore,
        settings: AppSettings,
        configuration: AppConfiguration,
        runtimeMode: AppRuntimeMode = .standard,
        acceptanceResetPending: Bool = false
    ) {
        self.api = api
        self.database = database
        self.credentials = credentials
        self.outbox = OutboxProcessor(database: database, api: api)
        self.settings = settings
        self.location = LocationClient()
        // Fixture UI tests exercise product state through PreviewAPIClient.
        // They must not initialize a real commerce SDK or turn a provider
        // alert into an unrelated UI-test interruption.
        let processArguments = ProcessInfo.processInfo.arguments
        let seedsPendingBlueConfirmation = runtimeMode == .uiTesting
            && processArguments.contains("-blueConfirmationPending")
        let seedsLifetimeBlueOwnership = runtimeMode == .uiTesting
            && processArguments.contains("-blueLifetimeOwned")
        self.billing = BillingModel(
            apiKey: runtimeMode == .uiTesting ? nil : configuration.revenueCatAPIKey,
            initialPackages: BillingModel.initialPackages(forUITesting: runtimeMode == .uiTesting),
            initialClientPremium: seedsPendingBlueConfirmation || seedsLifetimeBlueOwnership,
            initialHasActiveSubscription: seedsPendingBlueConfirmation
        )
        self.configuration = configuration
        self.runtimeMode = runtimeMode
        self.acceptanceResetPending = acceptanceResetPending
    }

    static func make() -> AppEnvironment {
        let configuration = AppConfiguration.current
        let arguments = ProcessInfo.processInfo.arguments
        let runtimeMode = AppRuntimeMode.resolve(arguments: arguments)
        guard runtimeMode != .liveAcceptance || AppRuntimeMode.permitsLiveAcceptanceBaseURL(configuration.apiBaseURL) else {
            fatalError("-liveAcceptance refuses non-loopback API origins")
        }
        guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
            fatalError("IlliniCover requires a bundle identifier for isolated credentials")
        }
        let storageIdentity = AppStorageIdentity.resolve(
            bundleIdentifier: bundleIdentifier,
            deploymentEnvironment: configuration.deploymentEnvironment,
            runtimeMode: runtimeMode
        )
        let credentials = CredentialStore(service: storageIdentity.credentialService)
        let database: AppDatabase
        do {
            switch runtimeMode {
            case .standard: database = try .production(namespace: storageIdentity.databaseNamespace)
            case .uiTesting: database = try .temporary()
            case .liveAcceptance: database = try .liveAcceptance()
            }
        } catch {
            fatalError("Unable to open the local IlliniCover database: \(error)")
        }
        let api: any AppAPI
#if DEBUG
        let seedsPrivacyTransition = runtimeMode == .uiTesting && (
            arguments.contains("-seedPrivacyTransition")
                || arguments.contains("-seedMismatchedPrivacyTransition")
        )
        if runtimeMode == .uiTesting && seedsPrivacyTransition {
            let attempts = PreviewDeletionAttemptCounter()
            api = PreviewAPIClient(
                deleteAccountBehavior: {
                    if await attempts.next() == 1 {
                        throw APIClientError.transport("privacy_recovery_offline")
                    }
                }
            )
        } else if runtimeMode == .uiTesting {
            let scenario = CanonicalFixtureSupport.scenario(arguments: arguments)
            guard let fixtureClient = CanonicalFixtureSupport.makeClient(scenario: scenario) else {
                fatalError("Canonical API fixtures are missing from the fixture UI-test bundle")
            }
            api = PreviewAPIClient(
                premiumAfterAuthentication: !arguments.contains("-signedInFree"),
                canonicalFixtureClient: fixtureClient
            )
        } else {
            // `-liveAcceptance` intentionally reaches this production-shaped
            // path. Its isolation is local storage only; all /api/v2 reads and
            // writes still compile and execute through the generated client.
            api = LiveAPIClient(baseURL: configuration.apiBaseURL, credentials: credentials)
        }
#else
        let seedsPrivacyTransition = false
        api = LiveAPIClient(baseURL: configuration.apiBaseURL, credentials: credentials)
#endif
        let resetLiveAcceptance = runtimeMode == .liveAcceptance && arguments.contains("-resetLiveAcceptance")
#if DEBUG
        let resetLocalState = runtimeMode == .standard
            && configuration.deploymentEnvironment == .local
            && arguments.contains("-resetLocalState")
#else
        let resetLocalState = false
#endif
        let resetUITestState = runtimeMode == .uiTesting
            && arguments.contains("-resetUITestState")
        let resetRequested = resetLiveAcceptance || resetLocalState || resetUITestState
        guard let isolatedDefaults = UserDefaults(suiteName: storageIdentity.defaultsSuite) else {
            fatalError("Unable to open isolated IlliniCover settings for \(storageIdentity.defaultsSuite)")
        }
        if resetLiveAcceptance {
            isolatedDefaults.removePersistentDomain(forName: storageIdentity.defaultsSuite)
        }
        if resetLocalState {
            isolatedDefaults.removePersistentDomain(forName: storageIdentity.defaultsSuite)
        }
        let settings = AppSettings(defaults: isolatedDefaults)
        if runtimeMode != .standard && arguments.contains("-skipOnboarding") {
            settings.onboardingComplete = true
        }
        if runtimeMode != .standard && arguments.contains("-resetOnboarding") {
            settings.onboardingComplete = false
        }
        if seedsPrivacyTransition {
            settings.pendingPrivacyTransition = .deleteAccount
            settings.pendingPrivacyRequestID = "11111111-1111-4111-8111-111111111111"
        } else if ProcessInfo.processInfo.arguments.contains("-uiTesting") {
            settings.pendingPrivacyTransition = .none
            settings.pendingPrivacyRequestID = nil
        }
        return AppEnvironment(
            api: api,
            database: database,
            credentials: credentials,
            settings: settings,
            configuration: configuration,
            runtimeMode: runtimeMode,
            acceptanceResetPending: resetRequested
        )
    }

    func bootstrap() async {
        if let bootstrapTask {
            await bootstrapTask.value
            return
        }
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performBootstrap()
        }
        bootstrapTask = task
        await task.value
    }

    private func performBootstrap() async {
        defer { isBootstrapping = false }
        if acceptanceResetPending {
            do {
                logger.notice("Starting local visual-acceptance reset")
                try await database.resetLocalData()
                logger.notice("Visual-acceptance database reset completed")
                try await credentials.deleteAllRequired()
                logger.notice("Visual-acceptance credential reset completed")
                acceptanceResetPending = false
            } catch {
                logger.error("Local visual-acceptance reset failed closed")
                globalNotice = "Acceptance-state reset failed. Product data stays hidden."
                return
            }
        }
        if runtimeMode == .uiTesting && ProcessInfo.processInfo.arguments.contains("-seedPrivacyTransition") {
            try? await credentials.writeRequired(
                "11111111-1111-4111-8111-111111111111",
                for: .pendingDeletionAccountID
            )
        } else if runtimeMode == .uiTesting && ProcessInfo.processInfo.arguments.contains("-seedMismatchedPrivacyTransition") {
            try? await credentials.writeRequired(
                "22222222-2222-4222-8222-222222222222",
                for: .pendingDeletionAccountID
            )
        }
        do {
            let linkedAccountID = try await credentials.readRequired(.linkedAccountID)
            let accountLinkConflict = try await credentials.readRequired(.accountLinkConflict)
            hasAccountLinkConflict = accountLinkConflict != nil
            installationMayRemainAccountLinked = settings.pendingLinkRequestID != nil
                || linkedAccountID != nil
                || accountLinkConflict != nil
        } catch {
            // An unreadable ownership marker must fail closed. The separate
            // installation probe will leave delivery unavailable if recovery
            // cannot prove whether an account-erasure boundary was crossed.
            installationMayRemainAccountLinked = true
            hasAccountLinkConflict = true
            logger.error("Unable to read the durable installation ownership marker")
        }
        if hasAccountLinkConflict {
            globalNotice = Self.accountLinkConflictNotice
        }
        let requiresOwnershipValidationBeforeDelivery = installationMayRemainAccountLinked
        if requiresOwnershipValidationBeforeDelivery {
            // Connectivity callbacks must not race the side-effect-free actor
            // probe after relaunch. If that probe proves revocation, retained
            // exact payloads are purged before delivery; if it is offline, a
            // later delivery 401 still consumes the same durable marker.
            await outbox.suspendAndWait()
        }
        await outbox.start(
            statusHandler: { [weak self] status in self?.outboxStatus = status },
            deliveryReadiness: { [weak self] in
                guard let self else { return false }
                return await self.prepareOutboxDelivery()
            },
            unauthorizedRecovery: { [weak self] in
                guard let self else { return .unavailable }
                return await self.recoverRevokedInstallation()
            }
        )
        if settings.pendingPrivacyTransition != .none {
            await outbox.suspendAndWait()
            guard await recoverPendingPrivacyTransition() else {
                globalNotice = pendingPrivacyNotice
                return
            }
        }
        do {
            try await ensureInstallation()
            let arguments = ProcessInfo.processInfo.arguments
            if runtimeMode == .uiTesting && (
                arguments.contains("-signedIn") || arguments.contains("-signedInFree")
            ) {
                let response = try await api.verifyEmailCode(code: "BCDF-GHJK", intent: .signIn)
                try await didAuthenticate(response.account)
            } else if runtimeMode == .uiTesting && !ProcessInfo.processInfo.arguments.contains("-preserveUITestAccount") {
                account = nil
                premium = false
            } else if await credentials.read(.sessionToken) != nil {
                try await refreshAccount()
            }
        } catch APIClientError.unauthorized {
            await handleInvalidAccountSession()
        } catch {
            logger.notice("Bootstrap continuing in guest/offline mode")
        }
        await validateCurrentInstallation()
        if requiresOwnershipValidationBeforeDelivery && !hasAccountLinkConflict {
            await outbox.resume()
        }
        await outbox.drain()
    }

    func didEnterForeground() async {
        guard !isBootstrapping else { return }
        // Lifecycle notices remain until the user dismisses them or a newer
        // lifecycle result replaces them. Foregrounding never hides one.
        if settings.pendingPrivacyTransition != .none {
            await outbox.suspendAndWait()
            guard await recoverPendingPrivacyTransition() else {
                globalNotice = pendingPrivacyNotice
                return
            }
        }
        await validateAuthenticatedForegroundState()
        await validateCurrentInstallation()
        guard await prepareOutboxDelivery() else { return }
        await outbox.drain()
        if account != nil { await refreshEntitlement() }
    }

    func retryFailedSubmissions() async {
        await outbox.retryFailed()
        await refreshFailedSubmissions()
    }

    func refreshFailedSubmissions() async {
        failedSubmissions = (try? await database.failedOutboxSummaries()) ?? []
    }

    func discardFailedSubmissions() async {
        await outbox.discardFailed()
        await refreshFailedSubmissions()
    }

    func didAuthenticate(_ account: AccountSummary) async throws {
        if settings.pendingPrivacyTransition == .deleteAccount {
            guard try await credentials.readRequired(.pendingDeletionAccountID) == account.id else {
                try? await api.signOut()
                try? await credentials.deleteRequired(.sessionToken)
                throw APIClientError.deletionAccountMismatch
            }
            guard await recoverPendingPrivacyTransition() else {
                throw APIClientError.destructiveRequestUnconfirmed
            }
            return
        }
        guard settings.pendingPrivacyTransition == .none else {
            throw APIClientError.destructiveRequestUnconfirmed
        }
        let requestID = settings.pendingLinkRequestID ?? UUID().uuidString
        settings.pendingLinkRequestID = requestID
        installationMayRemainAccountLinked = true
        do {
            try await api.linkInstallation(requestID: requestID)
        } catch let APIClientError.server(payload, status) where status == 409 && payload.code == "installation_already_linked" {
            // Never show or bill account B while this installation's durable
            // deletion/privacy ownership still belongs to another account.
            // Persist that fact without recording B's identifier. It remains
            // an erasure boundary across relaunch until verified actor
            // rotation, revocation, or account deletion retires the actor.
            await outbox.suspendAndWait()
            do {
                try await credentials.writeRequired("linked-elsewhere", for: .accountLinkConflict)
                settings.pendingLinkRequestID = nil
            } catch {
                // Keep the pending UUID as a durable fallback marker if the
                // Keychain write fails; never clear both ownership signals.
                logger.error("Unable to persist the account-link conflict marker")
            }
            try? await api.signOut()
            try? await credentials.deleteRequired(.sessionToken)
            self.account = nil
            premium = false
            billing.disableForSignedOutState()
            hasAccountLinkConflict = true
            installationMayRemainAccountLinked = true
            globalNotice = Self.accountLinkConflictNotice
            throw APIClientError.installationAlreadyLinked
        } catch {
            // The link may have committed before a response was lost. Retain
            // the session and request UUID so bootstrap can replay the exact
            // operation; do not show or bill the account before confirmation.
            self.account = nil
            premium = false
            billing.disableForSignedOutState()
            throw error
        }
        try await credentials.writeRequired(account.id, for: .linkedAccountID)
        try await credentials.deleteRequired(.accountLinkConflict)
        settings.pendingLinkRequestID = nil
        let resolvedAccountLinkConflict = hasAccountLinkConflict
        hasAccountLinkConflict = false
        installationMayRemainAccountLinked = true
        self.account = account
        await billing.configure(for: account.id)
        await refreshEntitlement()
        if resolvedAccountLinkConflict {
            await outbox.resume()
        }
    }

    func refreshAccount() async throws {
        let account = try await api.me()
        try await didAuthenticate(account)
    }

    @discardableResult
    func refreshEntitlement() async -> Bool {
        guard account != nil else {
            premium = false
            return true
        }
        do {
            let entitlements = try await api.entitlements()
            premium = entitlements.premium
            return true
        } catch {
            return false
        }
    }

    func signOut() async throws {
        guard settings.pendingPrivacyTransition == .none else {
            throw APIClientError.destructiveRequestUnconfirmed
        }
        try await api.signOut()
        try await credentials.deleteRequired(.sessionToken)
        // Signing out ends only the account session. A pending link request
        // may already have committed before its response was lost, so retain
        // that durable erasure boundary until replay or actor validation
        // resolves it.
        account = nil
        premium = false
        billing.disableForSignedOutState()
    }

    func deleteAccount() async throws {
        if settings.pendingPrivacyTransition == .deleteAccount {
            guard await recoverPendingPrivacyTransition() else {
                throw APIClientError.destructiveRequestUnconfirmed
            }
            return
        }
        guard settings.pendingPrivacyTransition == .none else {
            throw APIClientError.destructiveRequestUnconfirmed
        }
        let deletingAccountID: String
        if let accountID = account?.id {
            deletingAccountID = accountID
        } else {
            deletingAccountID = try await api.me().id
        }
        await outbox.suspendAndWait()
        try await credentials.writeRequired(deletingAccountID, for: .pendingDeletionAccountID)
        settings.pendingPrivacyTransition = .deleteAccount
        let requestID = settings.pendingPrivacyRequestID ?? UUID().uuidString
        settings.pendingPrivacyRequestID = requestID
        // Local erasure is a precondition to the remote destructive write. If
        // this fails, the server request is never sent and no unlink can occur.
        try await purgePrivatePresentationState()
        do {
            try await api.deleteAccount(requestID: requestID)
            try await finishConfirmedAccountDeletion()
        } catch {
            // A response-loss check is unauthenticated and idempotent. A 401
            // from DELETE alone is never treated as proof of erasure.
            if (try? await api.accountDeletionCompleted(requestID: requestID)) == true {
                try await finishConfirmedAccountDeletion()
                return
            }
            throw APIClientError.destructiveRequestUnconfirmed
        }
    }

    func rotateGuestActor() async throws {
        if settings.pendingPrivacyTransition == .deleteAccount {
            throw APIClientError.destructiveRequestUnconfirmed
        }
        if settings.pendingPrivacyTransition == .rotateGuest {
            guard await recoverPendingPrivacyTransition() else {
                throw APIClientError.destructiveRequestUnconfirmed
            }
            return
        }
        await outbox.suspendAndWait()
        settings.pendingPrivacyTransition = .rotateGuest
        let requestID = settings.pendingPrivacyRequestID ?? UUID().uuidString
        settings.pendingPrivacyRequestID = requestID
        let replacement = try await pendingReplacementInstallationToken()
        guard let current = try await credentials.readRequired(.installationToken) else {
            throw APIClientError.unauthorized
        }
        try await database.resetLocalData()
        let token = try await api.rotateInstallation(
            requestID: requestID,
            replacementToken: replacement,
            authorizationToken: current
        )
        try await credentials.writeRequired(token, for: .installationToken)
        try await credentials.deleteRequired(.pendingInstallationToken)
        try await credentials.deleteRequired(.linkedAccountID)
        try await credentials.deleteRequired(.accountLinkConflict)
        hasAccountLinkConflict = false
        installationMayRemainAccountLinked = false
        settings.pendingPrivacyTransition = .none
        settings.pendingPrivacyRequestID = nil
        outboxStatus = .empty
        failedSubmissions = []
        await outbox.resume()
    }

    private func recoverPendingPrivacyTransition() async -> Bool {
        let transition = settings.pendingPrivacyTransition
        do {
            try await purgePrivatePresentationState()
            switch transition {
            case .none:
                return true
            case .deleteAccount:
                let requestID = settings.pendingPrivacyRequestID ?? UUID().uuidString
                settings.pendingPrivacyRequestID = requestID
                if (try? await api.accountDeletionCompleted(requestID: requestID)) == true {
                    try await finishConfirmedAccountDeletion()
                } else {
                    try await api.deleteAccount(requestID: requestID)
                    try await finishConfirmedAccountDeletion()
                }
            case .rotateGuest:
                let requestID = settings.pendingPrivacyRequestID ?? UUID().uuidString
                settings.pendingPrivacyRequestID = requestID
                let replacement = try await pendingReplacementInstallationToken()
                // Receipt resolution occurs before credential authentication,
                // so the replacement token recovers a committed/lost response.
                let token: String
                do {
                    token = try await api.rotateInstallation(
                        requestID: requestID,
                        replacementToken: replacement,
                        authorizationToken: replacement
                    )
                } catch let APIClientError.server(_, status) where status == 422 {
                    guard let current = try await credentials.readRequired(.installationToken) else { throw APIClientError.unauthorized }
                    token = try await api.rotateInstallation(
                        requestID: requestID,
                        replacementToken: replacement,
                        authorizationToken: current
                    )
                }
                try await credentials.writeRequired(token, for: .installationToken)
                try await credentials.deleteRequired(.pendingInstallationToken)
                try await credentials.deleteRequired(.linkedAccountID)
                try await credentials.deleteRequired(.accountLinkConflict)
                hasAccountLinkConflict = false
                installationMayRemainAccountLinked = false
                settings.pendingPrivacyTransition = .none
                settings.pendingPrivacyRequestID = nil
                await outbox.resume()
            }
            return true
        } catch {
            logger.error("Privacy transition recovery pending; network delivery remains disabled")
            return false
        }
    }

    /// Coalesces every bootstrap, foreground, and connectivity caller onto one
    /// idempotent issuance attempt. Main-actor methods can re-enter while the
    /// network awaits; without this single flight, two different proposed
    /// credentials can race under the same fresh app launch.
    func ensureInstallation() async throws {
        guard try await credentials.readRequired(.installationToken) == nil else { return }
        if let installationIssuance {
            try await installationIssuance.value
            return
        }
        let issuance = Task { @MainActor [self] in
            try await issueInstallation()
        }
        installationIssuance = issuance
        do {
            try await issuance.value
            installationIssuance = nil
        } catch {
            installationIssuance = nil
            throw error
        }
    }

    private func issueInstallation() async throws {
        guard try await credentials.readRequired(.installationToken) == nil else { return }
        let requestID = settings.pendingInstallationRequestID ?? UUID().uuidString
        settings.pendingInstallationRequestID = requestID
        let proposed = try await pendingReplacementInstallationToken()
        let token = try await api.createInstallation(
            requestID: requestID,
            installationToken: proposed
        )
        guard token == proposed else { throw APIClientError.invalidResponse }
        try await credentials.writeRequired(token, for: .installationToken)
        try await credentials.deleteRequired(.pendingInstallationToken)
        settings.pendingInstallationRequestID = nil
    }

    private func prepareOutboxDelivery() async -> Bool {
        guard canSubmitReports else {
            if hasAccountLinkConflict { globalNotice = Self.accountLinkConflictNotice }
            return false
        }
        do {
            try await ensureInstallation()
            return true
        } catch {
            logger.notice("Installation issuance remains pending; queued reports stay local")
            return false
        }
    }

    private func validateAuthenticatedForegroundState() async {
        let sessionToken = await credentials.read(.sessionToken)
        guard account != nil || sessionToken != nil else { return }
        do {
            let remoteAccount = try await api.me()
            if account?.id == remoteAccount.id {
                account = remoteAccount
            } else {
                try await didAuthenticate(remoteAccount)
            }
        } catch APIClientError.unauthorized {
            // A pending-code token never reaches this path, and an expired
            // authenticated session is still not proof of account deletion.
            // Disable account/billing access now, preserve local evidence, and
            // let an installation-authenticated delivery distinguish a valid
            // linked actor from one actually revoked by remote deletion.
            await handleInvalidAccountSession()
        } catch {
            logger.notice("Authenticated foreground validation deferred while offline")
        }
    }

    /// A session 401 can mean an expired login or an unfinished email-code
    /// challenge, so it is never proof of account deletion. The installation
    /// credential is the separate authority that the server revokes when a
    /// linked account is deleted. Probe it without mutation on every launch
    /// and foreground transition so even a device with an empty outbox can
    /// honor the remote erasure boundary.
    private func validateCurrentInstallation() async {
        guard settings.pendingPrivacyTransition == .none else { return }
        do {
            guard try await credentials.readRequired(.installationToken) != nil else { return }
            _ = try await api.currentInstallationActorID()
        } catch APIClientError.unauthorized {
            await outbox.suspendAndWait()
            _ = await recoverRevokedInstallation()
            // Recovery either installed a replacement or preserved enough
            // state for deliveryReadiness to retry issuance on connectivity.
            await outbox.resume()
        } catch {
            logger.notice("Installation validation deferred while offline")
        }
    }

    private func handleInvalidAccountSession() async {
        account = nil
        premium = false
        try? await credentials.deleteRequired(.sessionToken)
        billing.disableForSignedOutState()
        globalNotice = "Your account session ended. Reporting remains available; sign in again to restore IlliniCover Blue access."
    }

    private func recoverRevokedInstallation() async -> OutboxProcessor.UnauthorizedRecoveryDisposition {
        guard settings.pendingPrivacyTransition == .none else { return .unavailable }
        let linkedAccountID: String?
        let accountLinkConflict: String?
        do {
            linkedAccountID = try await credentials.readRequired(.linkedAccountID)
            accountLinkConflict = try await credentials.readRequired(.accountLinkConflict)
        } catch {
            logger.error("Unable to validate the local identity marker")
            return .unavailable
        }
        let crossedAccountErasureBoundary = linkedAccountID != nil
            || accountLinkConflict != nil
            || settings.pendingLinkRequestID != nil

        if crossedAccountErasureBoundary {
            // A linked account disappearing invalidates every linked actor.
            // Purge first so an old exact-location payload can never be
            // reintroduced under the fresh guest pseudonym.
            do {
                try await purgePrivatePresentationState()
            } catch {
                logger.error("Unable to complete local erasure after account revocation")
                return .unavailable
            }
            settings.pendingLinkRequestID = nil
            do {
                try await credentials.deleteRequired(.sessionToken)
                try await credentials.deleteRequired(.linkedAccountID)
                try await credentials.deleteRequired(.accountLinkConflict)
            } catch {
                logger.error("Unable to retire revoked account credentials")
                return .discard
            }
            hasAccountLinkConflict = false
            installationMayRemainAccountLinked = false
            await billing.retireDeletedAccountIdentity()
        }

        do {
            try await credentials.deleteRequired(.installationToken)
            try await credentials.deleteRequired(.pendingInstallationToken)
        } catch {
            logger.error("Unable to replace a revoked installation credential")
            return crossedAccountErasureBoundary ? .discard : .unavailable
        }
        settings.pendingInstallationRequestID = nil
        do {
            try await ensureInstallation()
            if crossedAccountErasureBoundary {
                globalNotice = "This account is no longer active. IlliniCover cleared its private local data and switched to a fresh guest identity. Reports saved before deletion were not resent."
                return .discard
            }
            globalNotice = "This guest identity was no longer active. IlliniCover created a fresh guest identity and kept queued reports for delivery."
            return .retry
        } catch {
            if crossedAccountErasureBoundary {
                globalNotice = "This account is no longer active. Private local data was cleared; IlliniCover will create a fresh guest identity when the network is available."
                // The erasure completed even though guest issuance did not.
                // The caller must still discard its in-memory copy.
                return .discard
            }
            globalNotice = "This guest identity is no longer active. Saved reports remain on this device until a fresh guest identity can be created."
            return .unavailable
        }
    }

    private var pendingPrivacyNotice: String {
        switch settings.pendingPrivacyTransition {
        case .deleteAccount:
            "Account deletion is pending server confirmation. Private local data remains cleared and reporting is paused."
        case .rotateGuest:
            "Guest identity deletion is pending server confirmation. Private local data remains cleared and reporting is paused."
        case .none:
            ""
        }
    }

    private func pendingReplacementInstallationToken() async throws -> String {
        if let token = try await credentials.readRequired(.pendingInstallationToken) { return token }
        let token = try CredentialStore.makeInstallationToken()
        try await credentials.writeRequired(token, for: .pendingInstallationToken)
        return token
    }

    private func purgePrivatePresentationState() async throws {
        try await database.resetLocalData()
        account = nil
        premium = false
        outboxStatus = .empty
        billing.disableForSignedOutState()
    }

    private func finishConfirmedAccountDeletion() async throws {
        // Clear the old authority once. If fresh installation issuance loses
        // its response, preserve its request UUID and proposed token so the
        // next recovery attempt replays the same idempotent operation.
        let retainedSession = try await credentials.readRequired(.sessionToken)
        let retainedInstallation = try await credentials.readRequired(.installationToken)
        if retainedSession != nil || retainedInstallation != nil {
            try await credentials.deleteRequired(.sessionToken)
            try await credentials.deleteRequired(.installationToken)
            try await credentials.deleteRequired(.pendingInstallationToken)
            settings.pendingInstallationRequestID = nil
        }
        settings.pendingLinkRequestID = nil
        try await credentials.deleteRequired(.linkedAccountID)
        try await credentials.deleteRequired(.accountLinkConflict)
        hasAccountLinkConflict = false
        installationMayRemainAccountLinked = false
        await billing.retireDeletedAccountIdentity()
        try await ensureInstallation()
        try await credentials.deleteRequired(.pendingDeletionAccountID)
        settings.pendingPrivacyTransition = .none
        settings.pendingPrivacyRequestID = nil
        await outbox.resume()
    }
}

private actor PreviewDeletionAttemptCounter {
    private var count = 0
    func next() -> Int { count += 1; return count }
}
