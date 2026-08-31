import Foundation
import GRDB

private struct CacheRow: Codable, FetchableRecord, PersistableRecord {
    static let databaseTableName = "cache"
    let key: String
    let data: Data
    let fetchedAt: Date
}

enum OutboxKind: String, Codable, DatabaseValueConvertible, Sendable { case cover, deal }

struct OutboxEntry: Codable, FetchableRecord, PersistableRecord, Identifiable, Sendable {
    static let databaseTableName = "outbox"
    let id: String
    let kind: OutboxKind
    let data: Data
    let observedAt: Date
    var error: String?
}

struct OutboxStatus: Equatable, Sendable {
    let queued: Int
    let failed: Int
    static let empty = Self(queued: 0, failed: 0)
}

actor AppDatabase {
    private let db: DatabasePool
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    private init(path: String) throws {
        db = try DatabasePool(path: path)
        var migrator = DatabaseMigrator()
        migrator.registerMigration("current") { db in
            try db.create(table: "cache") {
                $0.column("key", .text).primaryKey()
                $0.column("data", .blob).notNull()
                $0.column("fetchedAt", .datetime).notNull()
            }
            try db.create(table: "outbox") {
                $0.column("id", .text).primaryKey()
                $0.column("kind", .text).notNull()
                $0.column("data", .blob).notNull()
                $0.column("observedAt", .datetime).notNull()
                $0.column("error", .text)
            }
        }
        try migrator.migrate(db)
    }

    static func production(namespace: String) throws -> AppDatabase {
        let parent = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let directory = parent.appending(path: "IlliniCover", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let path = directory.appending(path: "\(namespace).sqlite").path
        return try AppDatabase(path: path)
    }

    static func temporary() throws -> AppDatabase {
        try AppDatabase(path: FileManager.default.temporaryDirectory.appending(path: "IlliniCover-\(UUID()).sqlite").path)
    }

    func cached<Value: Decodable & Sendable>(_ type: Value.Type, key: String) async throws -> (Value, Date)? {
        guard let row = try await db.read({ try CacheRow.fetchOne($0, key: key) }) else { return nil }
        return (try decoder.decode(type, from: row.data), row.fetchedAt)
    }

    func cache<Value: Encodable & Sendable>(_ value: Value, key: String) async throws {
        let row = CacheRow(key: key, data: try encoder.encode(value), fetchedAt: .now)
        try await db.write { try row.save($0) }
    }

    func enqueue<Value: Encodable & Sendable>(id: String, kind: OutboxKind, observedAt: Date, value: Value) async throws {
        let row = OutboxEntry(id: id, kind: kind, data: try encoder.encode(value), observedAt: observedAt, error: nil)
        try await db.write { try row.save($0) }
    }

    func pendingOutbox() async throws -> [OutboxEntry] {
        try await db.read { try OutboxEntry.filter(Column("error") == nil).order(Column("observedAt")).fetchAll($0) }
    }

    func fail(id: String, error: String) async throws {
        _ = try await db.write { db in try OutboxEntry.filter(key: id).updateAll(db, Column("error").set(to: error)) }
    }

    func removeOutbox(id: String) async throws { _ = try await db.write { try OutboxEntry.deleteOne($0, key: id) } }
    func retryFailed() async throws { _ = try await db.write { try OutboxEntry.updateAll($0, Column("error").set(to: nil)) } }
    func discardFailed() async throws { _ = try await db.write { try OutboxEntry.filter(Column("error") != nil).deleteAll($0) } }

    func outboxStatus() async throws -> OutboxStatus {
        try await db.read { db in
            let failed = try OutboxEntry.filter(Column("error") != nil).fetchCount(db)
            return OutboxStatus(queued: try OutboxEntry.fetchCount(db) - failed, failed: failed)
        }
    }

    func resetLocalData() async throws {
        try await db.write { db in try CacheRow.deleteAll(db); try OutboxEntry.deleteAll(db) }
    }
}
