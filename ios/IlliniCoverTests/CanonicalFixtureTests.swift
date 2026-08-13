import Foundation
import Testing
@testable import IlliniCover

@Suite("Canonical API fixtures", .serialized)
struct CanonicalFixtureTests {
    private var fixtureDirectory: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "api/fixtures", directoryHint: .isDirectory)
    }

    private func client(_ scenario: CanonicalFixtureScenario = .rich) -> LiveAPIClient {
        LiveAPIClient(
            baseURL: URL(string: "https://canonical-fixtures.invalid")!,
            credentials: CredentialStore(service: "com.illinicover.tests.fixtures.\(UUID().uuidString)"),
            transport: CanonicalFixtureTransport(directory: fixtureDirectory, scenario: scenario)
        )
    }

    @Test("Backend-exported rich fixtures decode through generated production operations")
    func generatedFixtureTransport() async throws {
        let client = client()
        let board = try #require(try await client.coverBoard(eTag: nil).value)
        let deals = try #require(try await client.deals(eTag: nil).value)
        let suggestions = try await client.dealSuggestions(query: "wells", venueID: board.venues[0].venue.id)
        let detail = try await client.venueCover(id: board.venues[0].venue.id)
        let history = try await client.coverHistory(venueID: board.venues[0].venue.id)
        let timeMachine = try await client.timeMachine(venueID: board.venues[0].venue.id, target: board.generatedAt)

        #expect(board.venues.count >= 6)
        #expect(board.venues.contains { $0.cover.source == .advertised })
        #expect(deals.venues.first(where: { $0.venue.name == "Brothers" })?.deals.map(\.name) == [
            "Wells", "Busch Light", "Big Cups",
        ])
        #expect(suggestions.count == 6)
        #expect(suggestions.contains { $0.sourceScope == "venue" })
        #expect(suggestions.contains { $0.sourceScope == "global" })
        #expect(detail.recentReports.contains { $0.price == nil })
        #expect(history.accessTier == .limited)
        #expect(history.windowStart < timeMachine.knowledgeCutoff)
        #expect(history.reports.contains { $0.displayVibes.contains("Medium line") })
        #expect(timeMachine.venue.name == "KAMS")
    }

    @Test("Empty, historical, error, and offline scenarios stay honest")
    func sparseAndFailureScenarios() async throws {
        let emptyBoard = try #require(try await client(.empty).coverBoard(eTag: nil).value)
        let emptyDeals = try #require(try await client(.empty).deals(eTag: nil).value)
        #expect(!emptyBoard.venues.isEmpty)
        #expect(emptyBoard.venues.allSatisfy { $0.cover.price == .unavailable })
        #expect(!emptyDeals.venues.isEmpty)
        #expect(emptyDeals.venues.allSatisfy { $0.deals.isEmpty })
        #expect(try await client(.historical).coverBoard(eTag: nil).value?.venues.isEmpty == false)
        await #expect(throws: APIClientError.self) {
            _ = try await client(.error).venueCover(id: "missing")
        }
        await #expect(throws: APIClientError.self) {
            _ = try await client(.offline).coverBoard(eTag: nil)
        }
    }

    @Test("Fixture UI launch arguments select only named canonical scenarios")
    func scenarioArguments() {
        #expect(CanonicalFixtureSupport.scenario(arguments: ["app"]) == .rich)
        #expect(CanonicalFixtureSupport.scenario(arguments: ["app", "-fixtureScenario", "empty"]) == .empty)
        #expect(CanonicalFixtureSupport.scenario(arguments: ["app", "-fixtureScenario", "olderHistory"]) == .olderHistory)
        #expect(CanonicalFixtureSupport.scenario(arguments: ["app", "-fixtureScenario", "production"]) == .rich)
    }

    @Test("Older history stays reachable when the current service night has no reports")
    func olderHistoryWithoutCurrentReports() async throws {
        let scenarioClient = client(.olderHistory)
        let board = try #require(try await scenarioClient.coverBoard(eTag: nil).value)
        let emptyCurrentVenue = try #require(board.venues.first { $0.venue.slug == "unavailable" })
        let detail = try await scenarioClient.venueCover(id: emptyCurrentVenue.venue.id)
        let history = try await scenarioClient.coverHistory(venueID: emptyCurrentVenue.venue.id)

        #expect(detail.recentReports.isEmpty)
        #expect(history.accessTier == .limited)
        #expect(history.reports.count == 1)
        #expect(history.reports[0].observedAt < Date(timeIntervalSince1970: 1_786_581_600))
    }
}
