import Foundation
import Testing
@testable import IlliniCover

@Suite("Handbook cache semantics", .serialized)
struct HandbookTests {
    @Test("A definitive withdrawn-page 404 evicts and suppresses saved content") @MainActor
    func withdrawnPageEvictsCache() async throws {
        let database = try AppDatabase.temporary()
        let cached = Self.page
        try await database.cache(cached, key: "handbook-page-withdrawn-v2", etag: nil)
        let api = PreviewAPIClient(handbookPageBehavior: { _ in
            throw APIClientError.server(
                APIErrorPayload(code: "handbook_page_not_found", message: "Not found", requestId: nil),
                status: 404
            )
        })
        let environment = try makeEnvironment(api: api, database: database)
        let model = HandbookPageModel()

        await model.load(slug: "withdrawn", environment: environment)

        #expect(model.page == nil)
        #expect(!model.isOffline)
        #expect(model.errorMessage == "This handbook page is no longer available.")
        #expect(try await database.cached(HandbookPage.self, key: "handbook-page-withdrawn-v2") == nil)
    }

    @Test("A transport failure keeps an existing saved handbook page visible") @MainActor
    func offlineFailureKeepsCache() async throws {
        let database = try AppDatabase.temporary()
        let cached = Self.page
        try await database.cache(cached, key: "handbook-page-saved-v2", etag: nil)
        let api = PreviewAPIClient(handbookPageBehavior: { _ in
            throw APIClientError.transport("offline")
        })
        let environment = try makeEnvironment(api: api, database: database)
        let model = HandbookPageModel()

        await model.load(slug: "saved", environment: environment)

        #expect(model.page?.id == cached.id)
        #expect(model.isOffline)
        #expect(model.errorMessage == nil)
        #expect(try await database.cached(HandbookPage.self, key: "handbook-page-saved-v2") != nil)
    }

    @MainActor
    private func makeEnvironment(api: PreviewAPIClient, database: AppDatabase) throws -> AppEnvironment {
        let suffix = UUID().uuidString
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverHandbookTests.\(suffix)"))
        return AppEnvironment(
            api: api,
            database: database,
            credentials: CredentialStore(service: "com.illinicover.tests.handbook.\(suffix)"),
            settings: AppSettings(defaults: defaults),
            configuration: AppConfiguration(
                apiBaseURL: URL(string: "https://example.invalid")!,
                revenueCatAPIKey: nil
            )
        )
    }

    private static let page = HandbookPage(
        id: "saved",
        slug: "saved",
        title: "Saved page",
        summary: "Previously downloaded.",
        bodyMarkdown: "Saved body",
        updatedAt: Date(timeIntervalSince1970: 123)
    )
}
