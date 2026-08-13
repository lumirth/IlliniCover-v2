import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing
@testable import IlliniCover

@Suite("Generated production client contract", .serialized)
struct GeneratedClientContractTests {
    @Test("RFC3339 transport accepts whole and fractional seconds")
    func flexibleDateTimeTransport() throws {
        let transcoder = RFC3339DateTranscoder()
        let whole = try transcoder.decode("2026-08-12T21:15:00Z")
        let fractional = try transcoder.decode("2026-08-12T21:15:00.125Z")
        #expect(fractional.timeIntervalSince(whole) == 0.125)
        #expect(try transcoder.encode(fractional).contains(".125"))
    }

    @Test("Identity receipts compare UUID identity independent of server letter case")
    func identityReceiptUUIDCase() async throws {
        let requestID = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        let token = "ic_install_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        let transport = RecordingTransport(responses: [
            .json(
                status: 201,
                #"{"actorId":"11111111-1111-4111-8111-111111111111","requestId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","token":"ic_install_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}"#
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.installation-case.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        #expect(try await client.createInstallation(requestID: requestID, installationToken: token) == token)
        #expect(try #require(await transport.calls.first).operationID == Operations.CreateInstallation.id)
    }

    @Test("Installation validity probe uses the generated non-mutating operation")
    func currentInstallationProbe() async throws {
        let actorID = "11111111-1111-4111-8111-111111111111"
        let transport = RecordingTransport(responses: [
            .json(status: 200, #"{"actorId":"11111111-1111-4111-8111-111111111111"}"#),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.installation-probe.\(UUID().uuidString)")
        try await credentials.writeRequired("installation-secret", for: .installationToken)
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        #expect(try await client.currentInstallationActorID() == actorID)
        let call = try #require(await transport.calls.first)
        #expect(call.operationID == Operations.GetCurrentInstallation.id)
        #expect(call.path == "/api/v2/installations/current")
        #expect(call.headers[HTTPField.Name("X-Installation-Token")!] == "installation-secret")
        try await credentials.deleteRequired(.installationToken)
    }

    @Test("Status and venue deals use their generated operations")
    func remainingReadOperations() async throws {
        let transport = RecordingTransport(responses: [
            .json(status: 200, #"{"status":"ok"}"#),
            .json(
                status: 200,
                #"{"deals":[],"venue":{"address":"102 E Green St","id":"kams","name":"KAMS","openedYear":1933,"slug":"kams"}}"#
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.remaining.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        #expect(try await client.status() == "ok")
        let deals = try await client.venueDeals(venueID: "kams", eTag: "venue-etag")
        #expect(deals.value?.venue.name == "KAMS")

        let calls = await transport.calls
        #expect(calls.map(\.operationID) == [Operations.GetStatus.id, Operations.GetVenueDeals.id])
        #expect(calls[1].headers[.ifNoneMatch] == "venue-etag")
    }

    @Test("Deal suggestions preserve scope, last-seen, and alias-match metadata from the generated contract")
    func dealSuggestionMetadata() async throws {
        let transport = RecordingTransport(responses: [
            .json(
                status: 200,
                ##"{"suggestions":[{"canonicalFamilyId":"11111111-1111-4111-8111-111111111111","canonicalName":"Well Drinks","category":"drink","discountPercent":null,"displayName":"Well Drinks","lastSeenServiceDateLocal":"2026-08-09","matchedSource":"alias","matchedText":"Happy Hour Rail Drinks","priceCents":400,"priceHighCents":null,"priceKind":"absolute","priceLowCents":null,"servingFormat":"16 oz","sourceScope":"venue","timingDescription":"All night","timingKnown":true,"unit":"pint","whileSuppliesLast":false},{"canonicalFamilyId":"11111111-1111-4111-8111-111111111111","canonicalName":"Well Drinks","category":"drink","discountPercent":null,"displayName":"Well Drinks","lastSeenServiceDateLocal":"2026-08-03","matchedSource":"unit","matchedText":"#50CentWells","priceCents":400,"priceHighCents":null,"priceKind":"absolute","priceLowCents":null,"servingFormat":"16 oz","sourceScope":"global","timingDescription":"Before 10:00 PM","timingKnown":true,"unit":"can","whileSuppliesLast":false},{"canonicalFamilyId":"22222222-2222-4222-8222-222222222222","canonicalName":"Pitcher","category":"drink","discountPercent":null,"displayName":"Pitcher","lastSeenServiceDateLocal":"2026-07-31","matchedSource":"historical_alias","matchedText":null,"priceCents":600,"priceHighCents":null,"priceKind":"absolute","priceLowCents":null,"servingFormat":"","sourceScope":"global","timingDescription":null,"timingKnown":false,"unit":"pitcher","whileSuppliesLast":false}]}"##
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.suggestions.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        let suggestions = try await client.dealSuggestions(query: "well", venueID: "venue-kams")
        let suggestion = try #require(suggestions.first)
        #expect(suggestion.deal.name == "Well Drinks")
        #expect(suggestion.deal.serving == "16 oz · Pint")
        #expect(suggestion.deal.servingFormat == "16 oz")
        #expect(suggestion.deal.unit == "pint")
        #expect(suggestion.sourceScope == "venue")
        #expect(suggestion.lastSeenServiceDateLocal == "2026-08-09")
        #expect(suggestion.matchedSource == .alias)
        #expect(suggestion.matchedText == "Happy Hour Rail Drinks")
        #expect(suggestion.matchContextText == "Matched “Happy Hour Rail Drinks”")
        #expect(suggestions.map(\.sourceScope) == ["venue", "global", "global"])
        #expect(suggestions[1].deal.unit == "can")
        #expect(suggestions[1].deal.timing == .before("10:00 PM"))
        #expect(suggestions[1].matchedSource == .unit)
        #expect(suggestions[1].matchContextText == "Matched “#50CentWells”")
        #expect(suggestions[2].matchedSource == .historicalAlias)
        #expect(suggestions[2].matchedText == nil)
        #expect(suggestions[2].matchContextText == "Matched a historical deal name")
        #expect(suggestions[0].id != suggestions[1].id)
        let call = try #require(await transport.calls.first)
        #expect(call.operationID == Operations.SearchDealSuggestions.id)
        #expect(call.path.contains("q=well"))
        #expect(call.path.contains("venue=venue-kams"))
    }

    @Test("Cover board preserves exact latest evidence activity for shared venue sorting")
    func coverBoardLatestActivity() async throws {
        let venueID = "11111111-1111-4111-8111-111111111111"
        let transport = RecordingTransport(responses: [
            .json(
                status: 200,
                #"{"generatedAt":"2026-08-12T22:00:00Z","serverRevision":"test","serviceDate":"2026-08-12","venues":[{"cover":{"decisionId":"22222222-2222-4222-8222-222222222222","freshnessSeconds":60,"price":{"amountCents":2000,"kind":"single"},"source":"live","status":"current"},"latestActivityAt":"2026-08-12T21:59:00Z","recentReportCount":1,"venue":{"address":"102 E Green St","id":"11111111-1111-4111-8111-111111111111","name":"KAMS","openedYear":1933,"slug":"kams"},"vibes":{}}]}"#
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.cover-activity.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        let result = try await client.coverBoard(eTag: nil)
        let card = try #require(result.value?.venues.first)
        #expect(card.venue.id == venueID)
        #expect(card.latestActivityAt == ISO8601DateFormatter().date(from: "2026-08-12T21:59:00Z"))
        #expect(try #require(await transport.calls.first).operationID == Operations.GetCoverBoard.id)
    }

    @Test("Advertised-only conflicts never present as community reports")
    func advertisedConflictPresentation() async throws {
        let transport = RecordingTransport(responses: [
            .json(
                status: 200,
                #"{"generatedAt":"2026-08-12T22:00:00Z","serverRevision":"test","serviceDate":"2026-08-12","venues":[{"cover":{"decisionId":"22222222-2222-4222-8222-222222222222","freshnessSeconds":0,"price":{"amountCents":null,"highCents":1500,"kind":"range","lowCents":500},"source":"mixed","status":"advertised_conflict"},"latestActivityAt":"2026-08-12T21:59:00Z","recentReportCount":0,"venue":{"address":"522 E Green St","id":"11111111-1111-4111-8111-111111111111","name":"Legends","openedYear":1998,"slug":"legends"},"vibes":{"crowdLevel":null,"lineLength":null,"lineSpeed":null}}]}"#
            ),
        ])
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: CredentialStore(service: "com.illinicover.tests.generated.advertised-conflict.\(UUID().uuidString)"),
            transport: transport
        )

        let decision = try #require(try await client.coverBoard(eTag: nil).value?.venues.first?.cover)
        #expect(decision.isAdvertisedConflict)
        #expect(decision.presentationSourceLabel == "Advertised conflict")
        #expect(decision.sourcePill == "Advertised")
        #expect(decision.evidenceText == "Conflicting advertised prices")
        #expect(!decision.evidenceText.contains("Reported"))
        #expect(!decision.sourcePill.contains("Live"))
    }

    @Test("Vibe-only recent reports decode through the nullable generated cover history contract")
    func vibeOnlyCoverHistory() async throws {
        let transport = RecordingTransport(responses: [
            .json(
                status: 200,
                #"{"accessTier":"limited","hasMore":true,"reports":[{"broadContext":"near venue","interaction":"manual","observedAt":"2026-08-12T02:00:00Z","priceCents":null,"receivedAt":"2026-08-12T02:00:01Z","submissionId":"22222222-2222-4222-8222-222222222222","vibes":["line_length:medium","line_speed:fast","crowd_level:busy"]}],"serviceDate":"2026-08-11","venue":{"address":"102 E Green St","id":"11111111-1111-4111-8111-111111111111","name":"KAMS","openedYear":1933,"slug":"kams"},"windowStart":"2026-08-05T10:00:00Z"}"#
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.vibe-history.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        let history = try await client.coverHistory(venueID: "11111111-1111-4111-8111-111111111111")
        let report = try #require(history.reports.first)
        #expect(history.accessTier == .limited)
        #expect(history.hasMore)
        #expect(history.windowStart == ISO8601DateFormatter().date(from: "2026-08-05T10:00:00Z"))
        #expect(report.price == nil)
        #expect(report.vibes == ["line_length:medium", "line_speed:fast", "crowd_level:busy"])
        #expect(report.displayVibes == ["Medium line", "Fast line speed", "Busy"])
        #expect(report.locationContext == "near venue")
        #expect(try #require(await transport.calls.first).operationID == Operations.GetVenueCoverHistory.id)
    }

    @Test("Time Machine uses the generated target_time query")
    func timeMachineQuery() async throws {
        let venueID = "11111111-1111-4111-8111-111111111111"
        let transport = RecordingTransport(responses: [
            .value(
                status: 200,
                TimeMachineFixture(
                    cover: nil,
                    knowledgeCutoff: Date(timeIntervalSince1970: 1_754_965_800),
                    mode: .future,
                    targetTime: Date(timeIntervalSince1970: 1_754_965_860),
                    venue: .init(address: "102 E Green St", id: venueID, name: "KAMS", openedYear: nil, slug: "kams")
                )
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.time-machine.\(UUID().uuidString)")
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )

        let response = try await client.timeMachine(
            venueID: venueID,
            target: Date(timeIntervalSince1970: 1_754_965_861)
        )

        #expect(response.knowledgeCutoff == Date(timeIntervalSince1970: 1_754_965_800))
        // The server classified the unrounded request as future. The returned
        // minute can fall within the UI's current window, so never recompute.
        #expect(response.targetTime == Date(timeIntervalSince1970: 1_754_965_860))
        #expect(response.mode == .future)

        let call = try #require(await transport.calls.first)
        #expect(call.operationID == Operations.GetVenueCoverTimeMachine.id)
        #expect(call.path.contains("/api/v2/venues/\(venueID)/cover/time-machine"))
        #expect(call.path.contains("target_time="))
        #expect(!call.path.contains("?target="))
    }

    @Test("Time Machine preserves the generated typed rate-limit response")
    func timeMachineRateLimit() async throws {
        let transport = RecordingTransport(responses: [
            .json(status: 429, #"{"code":"rate_limited","message":"Try again later","requestId":"request-429"}"#),
        ])
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: CredentialStore(service: "com.illinicover.tests.generated.time-machine-429.\(UUID().uuidString)"),
            transport: transport
        )

        do {
            _ = try await client.timeMachine(
                venueID: "11111111-1111-4111-8111-111111111111",
                target: Date(timeIntervalSince1970: 1_754_965_861)
            )
            Issue.record("Expected typed 429")
        } catch let APIClientError.server(payload, status) {
            #expect(status == 429)
            #expect(payload.code == "rate_limited")
            #expect(payload.message == "Try again later")
        }
        #expect(try #require(await transport.calls.first).operationID == Operations.GetVenueCoverTimeMachine.id)
    }

    @Test("Generated deal request preserves range, canonical family, identity, and auth headers")
    func rangeDealRequest() async throws {
        let submissionID = "22222222-2222-4222-8222-222222222222"
        let transport = RecordingTransport(responses: [
            .value(
                status: 201,
                Components.Schemas.DealEvidenceReceiptSchema(
                    acceptedAt: Date(timeIntervalSince1970: 1_754_967_600),
                    duplicate: false,
                    eventId: "33333333-3333-4333-8333-333333333333",
                    submissionId: submissionID
                )
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.deal.\(UUID().uuidString)")
        await credentials.write("session-secret", for: .sessionToken)
        await credentials.write("installation-secret", for: .installationToken)
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )
        let request = DealEvidenceRequest(
            submissionId: submissionID,
            venueId: "11111111-1111-4111-8111-111111111111",
            observedAt: Date(timeIntervalSince1970: 1_754_967_600),
            action: .addMissing,
            targetDealId: nil,
            targetPredictionId: nil,
            submittedDeal: SubmittedDealShape(
                canonicalFamilyId: "family-pitcher",
                category: .drink,
                name: "Pitcher special",
                price: .range(500, 1_000),
                servingFormat: "64 oz",
                unit: "pitcher",
                timing: .allNight
            ),
            serviceDateLocal: "2026-08-11",
            targetLocalDateTime: nil
        )

        _ = try await client.submitDeal(request)

        let call = try #require(await transport.calls.first)
        #expect(call.operationID == Operations.CreateDealEvidence.id)
        #expect(call.path == "/api/v2/deal-evidence")
        #expect(call.headers[HTTPField.Name("X-Session-Token")!] == "session-secret")
        #expect(call.headers[HTTPField.Name("X-Installation-Token")!] == "installation-secret")
        #expect(call.headers[HTTPField.Name("X-Request-ID")!] != nil)
        let object = try #require(JSONSerialization.jsonObject(with: call.body) as? [String: Any])
        let shape = try #require(object["submittedDealShape"] as? [String: Any])
        #expect(shape["canonicalFamilyId"] as? String == "family-pitcher")
        #expect(shape["priceKind"] as? String == "range")
        #expect(shape["priceLowCents"] as? Int == 500)
        #expect(shape["priceHighCents"] as? Int == 1_000)
        #expect(shape["priceCents"] == nil)
        #expect(shape["servingFormat"] as? String == "64 oz")
        #expect(shape["unit"] as? String == "pitcher")
        await credentials.deleteAll()
    }

    @Test("Generated cover submission carries the optional authenticated session alongside installation auth")
    func coverSubmissionAuthHeaders() async throws {
        let submissionID = "44444444-4444-4444-8444-444444444444"
        let transport = RecordingTransport(responses: [
            .value(
                status: 201,
                Components.Schemas.SubmissionReceiptSchema(
                    acceptedAt: Date(timeIntervalSince1970: 1_754_967_600),
                    cover: nil,
                    duplicate: false,
                    submissionId: submissionID
                )
            ),
        ])
        let credentials = CredentialStore(service: "com.illinicover.tests.generated.cover-auth.\(UUID().uuidString)")
        try await credentials.writeRequired("session-secret", for: .sessionToken)
        try await credentials.writeRequired("installation-secret", for: .installationToken)
        let client = LiveAPIClient(
            baseURL: URL(string: "https://contract.invalid")!,
            credentials: credentials,
            transport: transport
        )
        let request = CoverSubmissionRequest(
            submissionId: submissionID,
            venueId: "11111111-1111-4111-8111-111111111111",
            observedAt: Date(timeIntervalSince1970: 1_754_967_600),
            vantagePoint: .outside,
            location: nil,
            cover: CoverObservationRequest(
                priceCents: 500,
                interaction: .manual,
                displayedDecisionId: nil,
                pricePrefilled: false,
                priceTouched: true
            ),
            vibes: []
        )

        _ = try await client.submitCover(request)

        let call = try #require(await transport.calls.first)
        #expect(call.operationID == Operations.CreateCoverSubmission.id)
        #expect(call.headers[HTTPField.Name("X-Session-Token")!] == "session-secret")
        #expect(call.headers[HTTPField.Name("X-Installation-Token")!] == "installation-secret")
        await credentials.deleteAll()
    }
}

private actor RecordingTransport: ClientTransport {
    struct Call: Sendable {
        let operationID: String
        let path: String
        let headers: HTTPFields
        let body: Data
    }

    struct Response: Sendable {
        let status: Int
        let body: String

        static func json(status: Int, _ body: String) -> Response {
            Response(status: status, body: body)
        }

        static func value<Value: Encodable>(status: Int, _ value: Value) -> Response {
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .custom { date, encoder in
                var container = encoder.singleValueContainer()
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                try container.encode(formatter.string(from: date))
            }
            return Response(status: status, body: String(decoding: try! encoder.encode(value), as: UTF8.self))
        }
    }

    private var responses: [Response]
    private(set) var calls: [Call] = []

    init(responses: [Response]) {
        self.responses = responses
    }

    func send(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String
    ) async throws -> (HTTPResponse, HTTPBody?) {
        let bytes: [UInt8]
        if let body {
            bytes = try await [UInt8](collecting: body, upTo: 1_048_576)
        } else {
            bytes = []
        }
        calls.append(Call(
            operationID: operationID,
            path: request.path ?? "",
            headers: request.headerFields,
            body: Data(bytes)
        ))
        let response = responses.removeFirst()
        var headers = HTTPFields()
        headers[.contentType] = "application/json"
        headers[.contentLength] = String(response.body.utf8.count)
        return (
            HTTPResponse(status: .init(code: response.status), headerFields: headers),
            HTTPBody(response.body)
        )
    }
}

private struct TimeMachineFixture: Encodable {
    struct VenueFixture: Encodable {
        let address: String
        let id: String
        let name: String
        let openedYear: Int?
        let slug: String
    }
    let cover: Components.Schemas.CoverStateSchema?
    let knowledgeCutoff: Date
    let mode: Components.Schemas.TimeMachineSchema.ModePayload
    let targetTime: Date
    let venue: VenueFixture

    private enum CodingKeys: String, CodingKey { case cover, knowledgeCutoff, mode, targetTime, venue }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeNil(forKey: .cover)
        try container.encode(knowledgeCutoff, forKey: .knowledgeCutoff)
        try container.encode(mode, forKey: .mode)
        try container.encode(targetTime, forKey: .targetTime)
        try container.encode(venue, forKey: .venue)
    }
}
