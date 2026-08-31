import Foundation
import Observation

enum IdentityTransitionError: LocalizedError {
    case pendingReports
    var errorDescription: String? { "Send or discard pending reports before changing accounts." }
}

@MainActor @Observable
final class AppEnvironment {
    private static let deferredLinkNotice = "Signed in. Account linking will retry when connected."
    let api: LiveAPIClient
    let database: AppDatabase
    let credentials: CredentialStore
    let settings: AppSettings
    let location = LocationClient()
    let billing: BillingModel
    let configuration: AppConfiguration
    let outbox: OutboxProcessor

    var account: AccountSummary?
    var premium = false
    var isBootstrapping = true
    var reportingReady = false
    var globalNotice: String?
    var outboxStatus = OutboxStatus.empty
    var pendingDeepLinkVenueID: String?
    private var installationRecovery: Task<Void, Error>?
    private var identityEpoch = 0
    private var activeSubmissions = 0
    private var submissionWaiters: [CheckedContinuation<Void, Never>] = []

    var canSubmitReports: Bool { reportingReady && !isBootstrapping }

    init(api: LiveAPIClient, database: AppDatabase, credentials: CredentialStore, settings: AppSettings, configuration: AppConfiguration) {
        self.api = api
        self.database = database
        self.credentials = credentials
        self.settings = settings
        self.configuration = configuration
        billing = BillingModel(apiKey: configuration.revenueCatAPIKey)
        outbox = OutboxProcessor(database: database, api: api)
    }

    static func make() -> AppEnvironment {
        let configuration = AppConfiguration.current
        guard let bundle = Bundle.main.bundleIdentifier else { fatalError("IlliniCover requires a bundle identifier") }
        let namespace = configuration.deployment.rawValue
        let credentials = CredentialStore(service: "\(bundle).credentials.\(namespace)")
        let defaults = UserDefaults(suiteName: "\(bundle).defaults.\(namespace)") ?? .standard
        let database = try! AppDatabase.production(namespace: namespace)
        let api = LiveAPIClient(baseURL: configuration.apiBaseURL, credentials: credentials)
        let environment = AppEnvironment(api: api, database: database, credentials: credentials, settings: AppSettings(defaults: defaults), configuration: configuration)
#if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("-resetLocalState") {
            defaults.removePersistentDomain(forName: "\(bundle).defaults.\(namespace)")
            environment.settings.onboardingComplete = false
        }
        if arguments.contains("-skipOnboarding") { environment.settings.onboardingComplete = true }
#endif
        return environment
    }

    func bootstrap() async {
        guard isBootstrapping else { return }
        do {
            let hasSession = try await credentials.read(.sessionToken) != nil
            if settings.accountDeletionUncertain && !hasSession {
                try await purgePrivateState()
                try await ensureInstallation()
            } else if hasSession { try await restoreSession() }
            else { try await ensureInstallation() }
        } catch { globalNotice = "Offline mode: reports will wait until a connection is available." }
        await outbox.start(status: { [weak self] in self?.outboxStatus = $0 }, invalidInstallation: { [weak self] in
            guard let self else { return }
            try? await self.recoverInvalidInstallation()
        })
        isBootstrapping = false
        if reportingReady { await outbox.resume(); await outbox.drain() }
    }

    func didEnterForeground() async {
        do {
            if try await credentials.read(.sessionToken) != nil { try await restoreSession() }
            else {
                if account != nil { account = nil; premium = false; await billing.retire() }
                try await ensureInstallation()
            }
        } catch { return }
        if reportingReady { await outbox.resume(); await outbox.drain() }
    }

    func ensureInstallation() async throws {
        if try await credentials.read(.installationToken) != nil {
            reportingReady = account == nil
            return
        }
        let token = try CredentialStore.makeInstallationToken()
        try await api.createInstallation(token: token)
        try await credentials.write(token, for: .installationToken)
        reportingReady = account == nil
    }

    func authenticate(_ code: String, intent: EmailCodeIntent) async throws {
        if reportingReady { await outbox.resume(); await outbox.drain() }
        let wasReady = reportingReady
        await invalidateReporting()
        guard try await database.outboxStatus() == .empty else {
            reportingReady = wasReady
            if wasReady { await outbox.resume() }
            throw IdentityTransitionError.pendingReports
        }
        do {
            let response = try await api.verifyEmailCode(code, intent: intent)
            try await finishAuthentication(response.account)
        } catch {
            if (try? await credentials.read(.sessionToken)) == nil {
                reportingReady = wasReady
                if wasReady { await outbox.resume() }
            }
            throw error
        }
    }

    func didAuthenticate(_ account: AccountSummary) async throws {
        await invalidateReporting()
        try await finishAuthentication(account)
    }

    func signOut() async throws {
        await invalidateReporting()
        if let old = try await credentials.read(.installationToken) {
            let replacement = try CredentialStore.makeInstallationToken()
            do { try await api.rotateInstallation(oldToken: old, newToken: replacement) }
            catch APIClientError.server(_, 422) {
                try await api.signOut(); settings.accountDeletionUncertain = false
                try await recoverInvalidInstallation(); return
            }
            try await credentials.write(replacement, for: .installationToken)
        } else { try await ensureInstallation() }
        try await api.signOut()
        settings.accountDeletionUncertain = false
        account = nil; premium = false; reportingReady = true
        await outbox.resume()
        await billing.retire()
    }

    func deleteAccount() async throws {
        let retryingUncertainDeletion = settings.accountDeletionUncertain
        let wasReady = reportingReady
        await invalidateReporting()
        settings.accountDeletionUncertain = true
        do { try await api.deleteAccount() }
        catch APIClientError.unauthorized {
            guard retryingUncertainDeletion else {
                settings.accountDeletionUncertain = false
                reportingReady = wasReady
                if wasReady { await outbox.resume() }
                throw APIClientError.unauthorized
            }
        } catch let error as APIClientError {
            if !error.retryable {
                settings.accountDeletionUncertain = false
                reportingReady = wasReady
                if wasReady { await outbox.resume() }
            }
            throw error
        } catch {
            settings.accountDeletionUncertain = false
            reportingReady = wasReady
            if wasReady { await outbox.resume() }
            throw error
        }
        try await purgePrivateState()
        try await ensureInstallation()
        await outbox.resume()
    }

    @discardableResult
    func refreshEntitlement() async -> Bool {
        do { premium = (try await api.entitlements()).premium; return true }
        catch { return false }
    }

    func rotateGuestActor() async throws {
        await invalidateReporting()
        guard let old = try await credentials.read(.installationToken) else {
            try await purgePrivateState(); try await ensureInstallation(); await outbox.resume(); return
        }
        let replacement = try CredentialStore.makeInstallationToken()
        do { try await api.rotateInstallation(oldToken: old, newToken: replacement) }
        catch APIClientError.server(_, 422) {
            try await purgePrivateState(); try await ensureInstallation(); await outbox.resume(); return
        }
        try await database.resetLocalData()
        try await credentials.deleteAll()
        try await credentials.write(replacement, for: .installationToken)
        account = nil; premium = false; reportingReady = true; await billing.retire()
        await outbox.resume()
    }

    func submitCover(_ request: CoverSubmissionRequest) async -> SubmissionOutcome {
        await submit(id: request.submissionId, kind: .cover, observedAt: request.observedAt, request) { try await api.submitCover(request) }
    }

    func submitDeal(_ request: DealEvidenceRequest) async -> SubmissionOutcome {
        await submit(id: request.submissionId, kind: .deal, observedAt: request.observedAt, request) { try await api.submitDeal(request) }
    }

    func retryFailedSubmissions() async { await outbox.retryFailed() }
    func discardFailedSubmissions() async { await outbox.discardFailed() }

    private func submit<Value: Encodable & Sendable>(id: String, kind: OutboxKind, observedAt: Date, _ value: Value,
                                                       send: () async throws -> Void) async -> SubmissionOutcome {
        guard canSubmitReports else { return .failed }
        var epoch = identityEpoch
        var result = await runSubmission(send)
        if case .failure(APIClientError.unauthorized) = result, epoch == identityEpoch {
            do {
                try await recoverInvalidInstallation()
                guard canSubmitReports else { return .failed }
                epoch = identityEpoch
                result = await runSubmission(send)
            } catch { return .failed }
        }
        guard epoch == identityEpoch else { return .failed }
        switch result {
        case .success: return .sent
        case .failure(let error as APIClientError) where error.retryable:
            guard epoch == identityEpoch else { return .failed }
            beginSubmission()
            defer { finishSubmission() }
            do {
                try await outbox.enqueue(id: id, kind: kind, observedAt: observedAt, value: value, drain: reportingReady)
                guard epoch == identityEpoch else {
                    try? await database.removeOutbox(id: id)
                    return .failed
                }
                return .queued
            }
            catch { return .failed }
        case .failure: return .failed
        }
    }

    private func runSubmission(_ send: () async throws -> Void) async -> Result<Void, Error> {
        beginSubmission()
        defer { finishSubmission() }
        do { try await send(); return .success(()) }
        catch { return .failure(error) }
    }

    private func beginSubmission() { activeSubmissions += 1 }

    private func finishSubmission() {
        activeSubmissions -= 1
        guard activeSubmissions == 0 else { return }
        let waiters = submissionWaiters
        submissionWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    private func linkInstallation() async throws {
        await suspendReporting()
        do {
            do { try await api.linkInstallation() }
            catch APIClientError.server(_, let status) where status == 409 || status == 422 {
                try await replaceInstallationPreservingSession()
                try await api.linkInstallation()
            }
            reportingReady = true
            await outbox.resume()
            if globalNotice == Self.deferredLinkNotice { globalNotice = nil }
        } catch let error as APIClientError where error.retryable {
            globalNotice = Self.deferredLinkNotice
        }
    }

    private func replaceInstallationPreservingSession() async throws {
        await invalidateReporting()
        if let old = try await credentials.read(.installationToken) {
            let replacement = try CredentialStore.makeInstallationToken()
            do {
                try await api.rotateInstallation(oldToken: old, newToken: replacement)
                try await credentials.write(replacement, for: .installationToken)
                return
            } catch APIClientError.server(_, 422) { }
        }
        try await credentials.delete(.installationToken)
        try await ensureInstallation()
        reportingReady = false
    }

    private func recoverInvalidInstallation() async throws {
        if let installationRecovery { try await installationRecovery.value; return }
        let recovery = Task { @MainActor [self] in
            await invalidateReporting()
            if try await credentials.read(.sessionToken) != nil {
                do {
                    account = try await api.me()
                    settings.accountDeletionUncertain = false
                } catch APIClientError.unauthorized {
                    try await purgePrivateState()
                    try await ensureInstallation()
                    await outbox.resume()
                    return
                }
            } else if account != nil {
                account = nil; premium = false; await billing.retire()
            }
            try await credentials.delete(.installationToken)
            try await ensureInstallation()
            if account != nil { try await linkInstallation() }
            else { reportingReady = true; await outbox.resume() }
        }
        installationRecovery = recovery
        defer { installationRecovery = nil }
        try await recovery.value
    }

    private func purgePrivateState() async throws {
        await invalidateReporting()
        try await database.resetLocalData()
        try await credentials.deleteAll()
        settings.reset()
        settings.accountDeletionUncertain = false
        account = nil; premium = false; await billing.retire()
    }

    private func suspendReporting() async {
        await outbox.suspendAndWait()
        if activeSubmissions > 0 {
            await withCheckedContinuation { submissionWaiters.append($0) }
        }
        reportingReady = false
    }

    private func invalidateReporting() async {
        identityEpoch += 1
        reportingReady = false
        await outbox.suspendAndWait()
        if activeSubmissions > 0 {
            await withCheckedContinuation { submissionWaiters.append($0) }
        }
    }

    private func restoreSession() async throws {
        do {
            account = try await api.me()
            settings.accountDeletionUncertain = false
            try await ensureInstallation()
            try await linkInstallation()
            if let account { await billing.configure(for: account.id) }
            premium = (try? await api.entitlements())?.premium ?? false
        } catch APIClientError.unauthorized {
            if settings.accountDeletionUncertain { try await purgePrivateState() }
            else {
                await suspendReporting()
                try await credentials.delete(.sessionToken)
                account = nil; premium = false; await billing.retire()
            }
            try await ensureInstallation()
        }
    }

    private func finishAuthentication(_ account: AccountSummary) async throws {
        settings.accountDeletionUncertain = false
        try await ensureInstallation()
        try await linkInstallation()
        self.account = account
        await billing.configure(for: account.id)
        _ = await refreshEntitlement()
        if reportingReady { await outbox.resume(); await outbox.drain() }
    }
}
