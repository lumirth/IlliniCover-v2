import Foundation
import Network

actor OutboxProcessor {
    private let database: AppDatabase
    private let api: LiveAPIClient
    private var monitor: NWPathMonitor?
    private var enabled = false
    private var draining = false
    private var suspensionWaiters: [CheckedContinuation<Void, Never>] = []
    private var status: (@MainActor @Sendable (OutboxStatus) -> Void)?
    private var invalidInstallation: (@MainActor @Sendable () async -> Void)?

    init(database: AppDatabase, api: LiveAPIClient) { self.database = database; self.api = api }
    deinit { monitor?.cancel() }

    func start(status: @escaping @MainActor @Sendable (OutboxStatus) -> Void,
               invalidInstallation: @escaping @MainActor @Sendable () async -> Void) async {
        self.status = status
        self.invalidInstallation = invalidInstallation
        await publish()
        guard monitor == nil else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] path in
            if path.status == .satisfied { Task { await self?.drain() } }
        }
        monitor.start(queue: DispatchQueue(label: "com.illinicover.outbox"))
        self.monitor = monitor
    }

    func resume() { enabled = true }

    func suspendAndWait() async {
        enabled = false
        guard draining else { return }
        await withCheckedContinuation { suspensionWaiters.append($0) }
    }

    func enqueue<Value: Encodable & Sendable>(id: String, kind: OutboxKind, observedAt: Date, value: Value, drain: Bool = true) async throws {
        try await database.enqueue(id: id, kind: kind, observedAt: observedAt, value: value)
        await publish()
        if drain { Task { await self.drain() } }
    }

    func drain() async {
        guard enabled, !draining else { return }
        draining = true
        var recoverInstallation = false
        do {
            for entry in try await database.pendingOutbox() {
                guard enabled else { break }
                do {
                    try await api.sendOutbox(entry)
                    try await database.removeOutbox(id: entry.id)
                } catch let error as APIClientError where error.retryable {
                    break
                } catch APIClientError.unauthorized {
                    guard enabled else { break }
                    recoverInstallation = true
                    break
                } catch {
                    guard enabled else { break }
                    try await database.fail(id: entry.id, error: "Server rejected this report")
                }
            }
        } catch { }
        draining = false
        let waiters = suspensionWaiters
        suspensionWaiters.removeAll()
        waiters.forEach { $0.resume() }
        await publish()
        if recoverInstallation { await invalidInstallation?() }
    }

    func retryFailed() async { try? await database.retryFailed(); await drain() }
    func discardFailed() async { try? await database.discardFailed(); await publish() }

    private func publish() async {
        guard let status, let value = try? await database.outboxStatus() else { return }
        await status(value)
    }
}
