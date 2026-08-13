import Foundation
import HTTPTypes
import OpenAPIRuntime

enum CanonicalFixtureScenario: String, Sendable {
    case rich
    case empty
    case historical
    case olderHistory
    case error
    case offline
}

enum CanonicalFixtureError: Error, Equatable {
    case resourcesUnavailable
    case missingFixture(String)
    case malformedFixture(String)
    case offline
}

/// Serves backend-exported JSON through the same generated OpenAPI client used
/// in production. The transport owns only scenario routing; it never recreates
/// response models in Swift.
actor CanonicalFixtureTransport: ClientTransport {
    private let directory: URL
    private let scenario: CanonicalFixtureScenario

    init(directory: URL, scenario: CanonicalFixtureScenario = .rich) {
        self.directory = directory
        self.scenario = scenario
    }

    func send(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String
    ) async throws -> (HTTPResponse, HTTPBody?) {
        if scenario == .offline { throw CanonicalFixtureError.offline }

        let response: (status: Int, data: Data)
        switch operationID {
        case Operations.GetStatus.id:
            response = (200, Data(#"{"status":"ok"}"#.utf8))
        case Operations.GetCoverBoard.id:
            let name = switch scenario {
            case .empty: "cover-board-empty"
            case .historical: "cover-board-historical"
            case .rich, .olderHistory, .error, .offline: "cover-board-rich"
            }
            response = (200, try fixture(named: name))
        case Operations.GetDealSlate.id:
            response = (200, try fixture(named: scenario == .empty ? "deals-empty" : "deals-rich"))
        case Operations.GetVenueDeals.id:
            response = try venueDealsResponse(path: request.path ?? "")
        case Operations.SearchDealSuggestions.id:
            response = (200, try fixture(named: "deal-suggestions-rich"))
        case Operations.GetVenueCover.id:
            if scenario == .error {
                response = (404, try fixture(named: "venue-not-found-error"))
            } else if scenario == .olderHistory {
                response = (200, try fixture(named: "venue-cover-no-current-reports"))
            } else {
                response = (200, try fixture(named: "venue-cover-rich"))
            }
        case Operations.GetVenueCoverHistory.id:
            response = (200, try fixture(named: scenario == .olderHistory ? "venue-cover-older-history" : "venue-cover-history-rich"))
        case Operations.GetVenueCoverTimeMachine.id:
            response = (200, try fixture(named: "time-machine-premium"))
        default:
            throw CanonicalFixtureError.missingFixture(operationID)
        }

        var fields = HTTPFields()
        fields[.contentType] = "application/json"
        fields[.contentLength] = String(response.data.count)
        fields[.eTag] = #""canonical-fixture-v1""#
        return (
            HTTPResponse(status: .init(code: response.status), headerFields: fields),
            HTTPBody(response.data)
        )
    }

    private func fixture(named name: String) throws -> Data {
        let url = directory.appending(path: "\(name).json")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw CanonicalFixtureError.missingFixture(name)
        }
        return try Data(contentsOf: url)
    }

    private func venueDealsResponse(path: String) throws -> (status: Int, data: Data) {
        let components = path.split(separator: "/")
        guard let venuesIndex = components.firstIndex(of: "venues"),
              components.indices.contains(venuesIndex + 1) else {
            throw CanonicalFixtureError.malformedFixture("getVenueDeals path")
        }
        let venueID = String(components[venuesIndex + 1])
        let data = try fixture(named: scenario == .empty ? "deals-empty" : "deals-rich")
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let venues = root["venues"] as? [[String: Any]],
              let match = venues.first(where: {
                  (($0["venue"] as? [String: Any])?["id"] as? String) == venueID
              }) else {
            return (404, try fixture(named: "venue-not-found-error"))
        }
        return (200, try JSONSerialization.data(withJSONObject: match, options: [.sortedKeys]))
    }
}

enum CanonicalFixtureSupport {
    static func directory(in bundle: Bundle = .main) -> URL? {
        if let bundled = bundle.url(
            forResource: "cover-board-rich",
            withExtension: "json",
            subdirectory: "fixtures"
        ) {
            return bundled.deletingLastPathComponent()
        }
        if let flattened = bundle.url(forResource: "cover-board-rich", withExtension: "json") {
            return flattened.deletingLastPathComponent()
        }
        return nil
    }

    static func makeClient(
        scenario: CanonicalFixtureScenario = .rich,
        directory: URL? = nil
    ) -> LiveAPIClient? {
        guard let directory = directory ?? Self.directory() else { return nil }
        return LiveAPIClient(
            baseURL: URL(string: "https://canonical-fixtures.invalid")!,
            credentials: CredentialStore(service: "com.illinicover.fixtures.credentials"),
            transport: CanonicalFixtureTransport(directory: directory, scenario: scenario)
        )
    }

    static func scenario(arguments: [String]) -> CanonicalFixtureScenario {
        guard let index = arguments.firstIndex(of: "-fixtureScenario"),
              arguments.indices.contains(index + 1),
              let scenario = CanonicalFixtureScenario(rawValue: arguments[index + 1]) else {
            return .rich
        }
        return scenario
    }
}
