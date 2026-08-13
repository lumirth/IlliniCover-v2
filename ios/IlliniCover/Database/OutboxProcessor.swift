import Foundation
import Network
import OSLog

actor OutboxProcessor {
    enum UnauthorizedRecoveryDisposition: Sendable {
        /// A replacement installation is ready and the same idempotent
        /// payload may be sent once more without changing its actor context.
        case retry
        /// Recovery proved an account-erasure boundary. The local row was
        /// purged and its in-memory payload must never be sent again.
        case discard
        /// Recovery could not finish; preserve the row for a later attempt.
        case unavailable
    }

    typealias StatusHandler = @MainActor @Sendable (OutboxStatus) -> Void
    typealias DeliveryReadiness = @MainActor @Sendable () async -> Bool
    typealias UnauthorizedRecovery = @MainActor @Sendable () async -> UnauthorizedRecoveryDisposition

    private let database: AppDatabase
    private let api: any OutboxSending
    private let logger = Logger(subsystem: "com.illinicover.app.v2", category: "outbox")
    private var monitor: NWPathMonitor?
    private var retryTask: Task<Void, Never>?
    private var isDraining = false
    private var isSuspended = false
    private var drainWaiters: [CheckedContinuation<Void, Never>] = []
    private var statusHandler: StatusHandler?
    private var deliveryReadiness: DeliveryReadiness?
    private var unauthorizedRecovery: UnauthorizedRecovery?

    init(database: AppDatabase, api: any OutboxSending) {
        self.database = database
        self.api = api
    }

    deinit {
        monitor?.cancel()
        retryTask?.cancel()
    }

    func start(
        statusHandler: @escaping StatusHandler,
        deliveryReadiness: DeliveryReadiness? = nil,
        unauthorizedRecovery: UnauthorizedRecovery? = nil
    ) async {
        self.statusHandler = statusHandler
        self.deliveryReadiness = deliveryReadiness
        self.unauthorizedRecovery = unauthorizedRecovery
        await publishStatus()
        guard monitor == nil else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied else { return }
            Task { await self?.drain() }
        }
        monitor.start(queue: DispatchQueue(label: "com.illinicover.app.v2.connectivity"))
        self.monitor = monitor
    }

    func retryFailed() async {
        guard !isSuspended else { return }
        do {
            try await database.retryFailedOutbox()
            await publishStatus()
            await drain()
        } catch {
            logger.error("Unable to retry failed outbox entries")
        }
    }

    func discardFailed() async {
        guard !isSuspended else { return }
        do {
            try await database.discardFailedOutbox()
            await publishStatus()
        } catch {
            logger.error("Unable to discard failed outbox entries")
        }
    }

    func enqueue<Value: Encodable & Sendable>(
        id: String,
        kind: OutboxKind,
        observedAt: Date,
        value: Value
    ) async throws {
        try await database.enqueue(id: id, kind: kind, observedAt: observedAt, value: value)
        await publishStatus()
        // Durable local acknowledgement must not wait for another URLSession
        // timeout. Connectivity and lifecycle triggers still perform the send.
        if !isSuspended {
            Task { [weak self] in await self?.drain() }
        }
    }

    func drain() async {
        guard !isSuspended else { return }
        if isDraining {
            await withCheckedContinuation { drainWaiters.append($0) }
            guard !isSuspended else { return }
            await drain()
            return
        }
        isDraining = true
        defer {
            isDraining = false
            let waiters = drainWaiters
            drainWaiters.removeAll()
            for waiter in waiters { waiter.resume() }
        }
        if let deliveryReadiness, !(await deliveryReadiness()) { return }
        retryTask?.cancel()
        retryTask = nil
        do {
            // Bound each actor turn to four batches, then schedule another
            // one-shot drain if more immediately-ready rows remain. This
            // prevents row 26+ from being stranded while keeping foreground
            // work cancellable and responsive.
            batchLoop: for _ in 0..<4 {
                let entries = try await database.pendingOutbox()
                guard !entries.isEmpty else { break }
                for entry in entries {
                    guard !Task.isCancelled, !isSuspended else { return }
                    do {
                        try await api.sendOutbox(kind: entry.submissionKind, payload: entry.payloadJSON)
                        // Delete only the exact acknowledged idempotency key.
                        try await database.removeOutbox(id: entry.id)
                    } catch {
                        var deliveryError = error
                        if case APIClientError.unauthorized = error,
                           let unauthorizedRecovery {
                            switch await unauthorizedRecovery() {
                            case .retry:
                                do {
                                    try await api.sendOutbox(kind: entry.submissionKind, payload: entry.payloadJSON)
                                    try await database.removeOutbox(id: entry.id)
                                    continue
                                } catch {
                                    deliveryError = error
                                }
                            case .discard:
                                // Account deletion is an erasure boundary. A
                                // database reset removed this row; never replay
                                // its retained in-memory location payload.
                                continue
                            case .unavailable:
                                // Identity recovery itself can be offline.
                                // Keep the original row queued instead of
                                // turning a recoverable credential outage into
                                // a permanent authorization failure.
                                deliveryError = APIClientError.transport("identity_recovery_pending")
                            }
                        }
                        let code = failureCode(for: deliveryError)
                        if isRetryable(deliveryError) {
                            try await database.markAttempt(id: entry.id, failureCode: code)
                            logger.notice("Outbox retry deferred")
                            break batchLoop
                        }
                        // A validation/authentication 4xx will not heal with
                        // backoff. Preserve it in the visible failed queue for
                        // deliberate user retry/correction and continue with
                        // independent entries.
                        try await database.markPermanentFailure(id: entry.id, failureCode: code)
                        logger.notice("Outbox entry needs user attention")
                    }
                }
                await Task.yield()
            }
            await publishStatus()
            await scheduleNextRetryIfNeeded()
        } catch {
            // Do not log serialized errors: transport and decoding failures
            // can contain request bodies, including precise location.
            logger.error("Unable to drain outbox")
        }
    }

    /// Stops future delivery and waits for any in-flight request to finish so
    /// an identity transition cannot race an old exact-location payload.
    func suspendAndWait() async {
        isSuspended = true
        retryTask?.cancel()
        retryTask = nil
        guard isDraining else { return }
        await withCheckedContinuation { drainWaiters.append($0) }
    }

    func resume() async {
        guard isSuspended else { return }
        isSuspended = false
        await publishStatus()
        await drain()
    }

    private func scheduleNextRetryIfNeeded() async {
        guard !isSuspended else { return }
        guard let retryAt = try? await database.nextOutboxRetryDate() else { return }
        let delay = max(0, min(retryAt.timeIntervalSinceNow, 15 * 60))
        retryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            await self?.drain()
        }
    }

    private func publishStatus() async {
        guard let statusHandler, let status = try? await database.outboxStatus() else { return }
        await statusHandler(status)
    }

    private func failureCode(for error: Error) -> String {
        switch error {
        case APIClientError.transport: "offline"
        case APIClientError.unauthorized: "unauthorized"
        case APIClientError.invalidConfiguration: "configuration"
        case APIClientError.invalidResponse: "invalid_response"
        case APIClientError.server(_, let status): "server_\(status)"
        case APIClientError.installationAlreadyLinked: "installation_link_conflict"
        case APIClientError.reportingPausedForAccountLinkConflict: "installation_link_conflict"
        case APIClientError.destructiveRequestUnconfirmed: "privacy_transition_unconfirmed"
        case APIClientError.deletionAccountMismatch: "deletion_account_mismatch"
        default: "unknown"
        }
    }

    private func isRetryable(_ error: Error) -> Bool {
        guard let error = error as? APIClientError else { return true }
        return error.isRetryableSubmissionFailure
    }
}
