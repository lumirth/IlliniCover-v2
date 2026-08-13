import Foundation
import GRDB

private enum AppDatabaseConfigurationError: Error {
    case invalidNamespace
}

struct CachedPayload: Codable, FetchableRecord, PersistableRecord, Sendable {
    static let databaseTableName = "api_cache"

    let key: String
    let payloadJSON: Data
    let etag: String?
    let fetchedAt: Date
    let serverGeneratedAt: Date?
    let expiresAt: Date?

    enum Columns: String, ColumnExpression {
        case key, payloadJSON = "payload_json", etag, fetchedAt = "fetched_at"
        case serverGeneratedAt = "server_generated_at", expiresAt = "expires_at"
    }

    private enum CodingKeys: String, CodingKey {
        case key, payloadJSON = "payload_json", etag, fetchedAt = "fetched_at"
        case serverGeneratedAt = "server_generated_at", expiresAt = "expires_at"
    }
}

enum OutboxKind: String, Codable, DatabaseValueConvertible, Sendable {
    case cover
    case deal
}

enum OutboxState: String, Codable, DatabaseValueConvertible, Sendable {
    case pending
    case retrying
    case failed
}

struct OutboxEntry: Codable, FetchableRecord, PersistableRecord, Identifiable, Sendable {
    static let databaseTableName = "submission_outbox"

    let id: String
    let submissionKind: OutboxKind
    let payloadJSON: Data
    let observedAt: Date
    let createdAt: Date
    var attemptCount: Int
    var lastAttemptAt: Date?
    var nextAttemptAt: Date?
    var lastError: String?
    var state: OutboxState

    enum Columns: String, ColumnExpression {
        case id, submissionKind = "submission_kind", payloadJSON = "payload_json"
        case observedAt = "observed_at", createdAt = "created_at"
        case attemptCount = "attempt_count", lastAttemptAt = "last_attempt_at"
        case nextAttemptAt = "next_attempt_at", lastError = "last_error", state
    }

    private enum CodingKeys: String, CodingKey {
        case id, submissionKind = "submission_kind", payloadJSON = "payload_json"
        case observedAt = "observed_at", createdAt = "created_at"
        case attemptCount = "attempt_count", lastAttemptAt = "last_attempt_at"
        case nextAttemptAt = "next_attempt_at", lastError = "last_error", state
    }
}

struct OutboxStatus: Equatable, Sendable {
    let queued: Int
    let failed: Int

    static let empty = OutboxStatus(queued: 0, failed: 0)
}

struct FailedSubmissionSummary: Identifiable, Equatable, Sendable {
    let id: String
    let kind: OutboxKind
    let observedAt: Date
    let failureCode: String

    var canRetryUnchanged: Bool {
        failureCode == "offline" || failureCode == "invalid_response"
            || failureCode == "configuration" || failureCode == "unknown"
            || failureCode.hasPrefix("server_5") || failureCode == "server_408"
            || failureCode == "server_429"
    }
}

actor AppDatabase {
    private let pool: DatabasePool
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let resetPreflight: (@Sendable () throws -> Void)?

    init(
        path: String,
        protection: FileProtectionType? = nil,
        resetPreflight: (@Sendable () throws -> Void)? = nil
    ) throws {
        self.resetPreflight = resetPreflight
        if let protection {
            try Self.applyProtection(protection, toDirectoryContaining: path)
        }
        var configuration = Configuration()
        configuration.foreignKeysEnabled = true
        configuration.busyMode = .timeout(5)
        configuration.prepareDatabase { db in
            db.trace(options: .statement) { _ in }
        }
        pool = try DatabasePool(path: path, configuration: configuration)

        var migrator = DatabaseMigrator()
        migrator.registerMigration("v1_cache_outbox") { db in
            try db.create(table: "api_cache") { table in
                table.column("key", .text).primaryKey()
                table.column("payload_json", .blob).notNull()
                table.column("etag", .text)
                table.column("fetched_at", .datetime).notNull()
                table.column("server_generated_at", .datetime)
                table.column("expires_at", .datetime)
            }
            try db.create(table: "submission_outbox") { table in
                table.column("id", .text).primaryKey()
                table.column("submission_kind", .text).notNull()
                table.column("payload_json", .blob).notNull()
                table.column("observed_at", .datetime).notNull()
                table.column("created_at", .datetime).notNull()
                table.column("attempt_count", .integer).notNull().defaults(to: 0)
                table.column("last_attempt_at", .datetime)
                table.column("last_error", .text)
                table.column("state", .text).notNull()
            }
            try db.create(index: "submission_outbox_pending", on: "submission_outbox", columns: ["state", "created_at"])
            try db.create(table: "local_metadata") { table in
                table.column("key", .text).primaryKey()
                table.column("value", .text).notNull()
            }
        }
        migrator.registerMigration("v2_outbox_backoff") { db in
            try db.alter(table: "submission_outbox") { table in
                table.add(column: "next_attempt_at", .datetime)
            }
        }
        try migrator.migrate(pool)
        if let protection {
            try Self.applyProtection(protection, toDatabaseAt: path)
        }

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    static func production(namespace: String, baseDirectory: URL? = nil) throws -> AppDatabase {
        guard !namespace.isEmpty,
              namespace.range(of: #"^[a-z0-9-]+$"#, options: .regularExpression) != nil else {
            throw AppDatabaseConfigurationError.invalidNamespace
        }
        let parent = try baseDirectory ?? FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = parent
            .appending(path: "IlliniCover", directoryHint: .isDirectory)
            .appending(path: namespace, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return try AppDatabase(
            path: directory.appending(path: "illinicover-\(namespace).sqlite").path,
            protection: .completeUntilFirstUserAuthentication
        )
    }

    static func liveAcceptance(baseDirectory: URL? = nil) throws -> AppDatabase {
        let parent = try baseDirectory ?? FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = parent.appending(path: "IlliniCoverLiveAcceptance", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return try AppDatabase(
            path: directory.appending(path: "live-acceptance.sqlite").path,
            protection: .completeUntilFirstUserAuthentication
        )
    }

    static func temporary() throws -> AppDatabase {
        let directory = FileManager.default.temporaryDirectory
            .appending(path: "IlliniCover-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return try AppDatabase(path: directory.appending(path: "test.sqlite").path)
    }

    func cached<Value: Decodable & Sendable>(_ type: Value.Type, key: String) async throws -> (Value, CachedPayload)? {
        guard let row = try await pool.read({ db in try CachedPayload.fetchOne(db, key: key) }) else { return nil }
        return (try decoder.decode(type, from: row.payloadJSON), row)
    }

    func cache<Value: Encodable & Sendable>(
        _ value: Value,
        key: String,
        etag: String?,
        fetchedAt: Date = .now,
        serverGeneratedAt: Date? = nil,
        expiresAt: Date? = nil
    ) async throws {
        let payload = try encoder.encode(value)
        let row = CachedPayload(
            key: key,
            payloadJSON: payload,
            etag: etag,
            fetchedAt: fetchedAt,
            serverGeneratedAt: serverGeneratedAt,
            expiresAt: expiresAt
        )
        try await pool.write { db in try row.save(db) }
    }

    func touchCache(key: String, fetchedAt: Date = .now, etag: String? = nil) async throws {
        try await pool.write { db in
            guard var row = try CachedPayload.fetchOne(db, key: key) else { return }
            row = CachedPayload(
                key: row.key,
                payloadJSON: row.payloadJSON,
                etag: etag ?? row.etag,
                fetchedAt: fetchedAt,
                serverGeneratedAt: row.serverGeneratedAt,
                expiresAt: row.expiresAt
            )
            try row.update(db)
        }
    }

    func removeCache(key: String) async throws {
        _ = try await pool.write { db in try CachedPayload.deleteOne(db, key: key) }
    }

    func enqueue<Value: Encodable & Sendable>(
        id: String,
        kind: OutboxKind,
        observedAt: Date,
        value: Value
    ) async throws {
        let entry = OutboxEntry(
            id: id,
            submissionKind: kind,
            payloadJSON: try encoder.encode(value),
            observedAt: observedAt,
            createdAt: .now,
            attemptCount: 0,
            lastAttemptAt: nil,
            nextAttemptAt: nil,
            lastError: nil,
            state: .pending
        )
        try await pool.write { db in try entry.insert(db, onConflict: .ignore) }
    }

    func pendingOutbox(limit: Int = 25, now: Date = .now) async throws -> [OutboxEntry] {
        try await pool.read { db in
            try OutboxEntry
                .filter(OutboxEntry.Columns.state != OutboxState.failed.rawValue)
                .filter(
                    OutboxEntry.Columns.nextAttemptAt == nil
                        || OutboxEntry.Columns.nextAttemptAt <= now
                )
                .order(OutboxEntry.Columns.createdAt.asc)
                .limit(limit)
                .fetchAll(db)
        }
    }

    func markAttempt(id: String, failureCode: String, now: Date = .now) async throws {
        try await pool.write { db in
            guard var entry = try OutboxEntry.fetchOne(db, key: id) else { return }
            entry.attemptCount += 1
            entry.lastAttemptAt = now
            entry.lastError = failureCode
            if entry.attemptCount >= 8 {
                entry.state = .failed
                entry.nextAttemptAt = nil
            } else {
                entry.state = .retrying
                let seconds = min(pow(2, Double(entry.attemptCount)), 15 * 60)
                entry.nextAttemptAt = now.addingTimeInterval(seconds)
            }
            try entry.update(db)
        }
    }

    func markPermanentFailure(id: String, failureCode: String, now: Date = .now) async throws {
        try await pool.write { db in
            guard var entry = try OutboxEntry.fetchOne(db, key: id) else { return }
            entry.attemptCount += 1
            entry.lastAttemptAt = now
            entry.lastError = failureCode
            entry.state = .failed
            entry.nextAttemptAt = nil
            try entry.update(db)
        }
    }

    func nextOutboxRetryDate() async throws -> Date? {
        try await pool.read { db in
            try Date.fetchOne(
                db,
                sql: "SELECT MIN(COALESCE(next_attempt_at, created_at)) FROM submission_outbox WHERE state != ?",
                arguments: [OutboxState.failed.rawValue]
            )
        }
    }

    func retryFailedOutbox() async throws {
        try await pool.write { db in
            try db.execute(
                sql: """
                UPDATE submission_outbox
                SET state = ?, attempt_count = 0, last_attempt_at = NULL,
                    next_attempt_at = NULL, last_error = NULL
                WHERE state = ? AND (
                    last_error IN ('offline', 'invalid_response', 'configuration', 'unknown', 'server_408', 'server_429')
                    OR last_error LIKE 'server_5%'
                )
                """,
                arguments: [OutboxState.pending.rawValue, OutboxState.failed.rawValue]
            )
        }
    }

    func failedOutboxSummaries() async throws -> [FailedSubmissionSummary] {
        try await pool.read { db in
            try OutboxEntry
                .filter(OutboxEntry.Columns.state == OutboxState.failed.rawValue)
                .order(OutboxEntry.Columns.observedAt.desc)
                .fetchAll(db)
                .map {
                    FailedSubmissionSummary(
                        id: $0.id,
                        kind: $0.submissionKind,
                        observedAt: $0.observedAt,
                        failureCode: $0.lastError ?? "unknown"
                    )
                }
        }
    }

    func discardFailedOutbox() async throws {
        _ = try await pool.write { db in
            try OutboxEntry
                .filter(OutboxEntry.Columns.state == OutboxState.failed.rawValue)
                .deleteAll(db)
        }
    }

    func removeOutbox(id: String) async throws {
        _ = try await pool.write { db in try OutboxEntry.deleteOne(db, key: id) }
    }

    func outboxCount() async throws -> Int {
        try await pool.read { db in try OutboxEntry.fetchCount(db) }
    }

    func outboxStatus() async throws -> OutboxStatus {
        try await pool.read { db in
            let failed = try OutboxEntry
                .filter(OutboxEntry.Columns.state == OutboxState.failed.rawValue)
                .fetchCount(db)
            return OutboxStatus(queued: try OutboxEntry.fetchCount(db) - failed, failed: failed)
        }
    }

    func resetLocalData() async throws {
        try resetPreflight?()
        try await pool.write { db in
            try CachedPayload.deleteAll(db)
            try OutboxEntry.deleteAll(db)
            try db.execute(sql: "DELETE FROM local_metadata")
        }
    }

    private static func applyProtection(_ protection: FileProtectionType, toDirectoryContaining path: String) throws {
        let directory = URL(fileURLWithPath: path).deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: protection]
        )
        try FileManager.default.setAttributes([.protectionKey: protection], ofItemAtPath: directory.path)
    }

    private static func applyProtection(_ protection: FileProtectionType, toDatabaseAt path: String) throws {
        let manager = FileManager.default
        for protectedPath in [path, "\(path)-wal", "\(path)-shm"] where manager.fileExists(atPath: protectedPath) {
            try manager.setAttributes([.protectionKey: protection], ofItemAtPath: protectedPath)
        }
    }
}
