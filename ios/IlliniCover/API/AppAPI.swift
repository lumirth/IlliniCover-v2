import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession
import OSLog

/// OpenAPI `date-time` is RFC 3339 and permits both whole-second and
/// fractional-second values. The backend legitimately emits both forms, so
/// the transport must not require a decimal point merely because iOS encodes
/// its own observations with one.
struct RFC3339DateTranscoder: DateTranscoder {
    private let fractional = ISO8601DateTranscoder(
        options: [.withInternetDateTime, .withFractionalSeconds]
    )
    private let wholeSeconds = ISO8601DateTranscoder(options: [.withInternetDateTime])

    func encode(_ date: Date) throws -> String {
        try fractional.encode(date)
    }

    func decode(_ string: String) throws -> Date {
        do {
            return try fractional.decode(string)
        } catch {
            return try wholeSeconds.decode(string)
        }
    }
}

struct HTTPResult<Value: Sendable>: Sendable {
    let value: Value?
    let eTag: String?
    let notModified: Bool
}

enum EmailCodeIntent: Hashable, Sendable {
    case signIn
    case signUp
}

struct EmailCodeChallenge: Sendable {
    let sessionToken: String
    let intent: EmailCodeIntent
}

enum APIClientError: LocalizedError, Sendable {
    case invalidConfiguration
    case invalidResponse
    case transport(String)
    case server(APIErrorPayload, status: Int)
    case unauthorized
    case installationAlreadyLinked
    case reportingPausedForAccountLinkConflict
    case destructiveRequestUnconfirmed
    case deletionAccountMismatch

    var errorDescription: String? {
        switch self {
        case .invalidConfiguration: "IlliniCover is not configured for a server."
        case .invalidResponse: "The server returned a response IlliniCover could not read."
        case .transport: "You appear to be offline."
        case .server(let payload, _): payload.message
        case .unauthorized: "Please sign in again."
        case .installationAlreadyLinked:
            "This installation belongs to another account. Sign in to that account or delete and rotate this installation before switching accounts or reporting."
        case .reportingPausedForAccountLinkConflict:
            "Reporting is paused because this installation belongs to another account. Sign in to that account or delete and rotate this installation."
        case .destructiveRequestUnconfirmed:
            "Private data was cleared from this device, but deletion is still awaiting server confirmation. IlliniCover will retry with the same private request receipt."
        case .deletionAccountMismatch:
            "Sign in to the same account that requested deletion. IlliniCover did not delete the account you just signed in to."
        }
    }

    var isRetryableSubmissionFailure: Bool {
        switch self {
        case .transport: true
        case .server(_, let status): status == 408 || status == 429 || status >= 500
        case .invalidConfiguration, .invalidResponse, .unauthorized,
             .installationAlreadyLinked, .reportingPausedForAccountLinkConflict,
             .destructiveRequestUnconfirmed, .deletionAccountMismatch: false
        }
    }

    var isUnauthorized: Bool {
        if case .unauthorized = self { return true }
        return false
    }
}

protocol OutboxSending: Sendable {
    func sendOutbox(kind: OutboxKind, payload: Data) async throws
}

protocol AppAPI: OutboxSending {
    func status() async throws -> String
    func createInstallation(requestID: String, installationToken: String) async throws -> String
    func currentInstallationActorID() async throws -> String
    func rotateInstallation(requestID: String, replacementToken: String, authorizationToken: String) async throws -> String
    func coverBoard(eTag: String?) async throws -> HTTPResult<CoverBoardResponse>
    func venueCover(id: String) async throws -> VenueCoverResponse
    func coverHistory(venueID: String) async throws -> CoverHistoryResponse
    func timeMachine(venueID: String, target: Date) async throws -> TimeMachineResponse
    func submitCover(_ request: CoverSubmissionRequest) async throws -> SubmissionReceipt
    func deals(eTag: String?) async throws -> HTTPResult<DealsResponse>
    func venueDeals(venueID: String, eTag: String?) async throws -> HTTPResult<VenueDeals>
    func dealSuggestions(query: String, venueID: String?) async throws -> [DealSuggestion]
    func submitDeal(_ request: DealEvidenceRequest) async throws -> SubmissionReceipt
    func handbook(eTag: String?) async throws -> HTTPResult<[HandbookPageSummary]>
    func handbookPage(slug: String) async throws -> HandbookPage
    func requestEmailCode(email: String, intent: EmailCodeIntent) async throws -> EmailCodeChallenge
    func resendEmailCode(intent: EmailCodeIntent) async throws
    func verifyEmailCode(code: String, intent: EmailCodeIntent) async throws -> AuthSessionResponse
    func me() async throws -> AccountSummary
    func signOut() async throws
    func deleteAccount(requestID: String) async throws
    func accountDeletionCompleted(requestID: String) async throws -> Bool
    func linkInstallation(requestID: String) async throws
    func entitlements() async throws -> EntitlementSummary
}

actor LiveAPIClient: AppAPI {
    private let logger = Logger(subsystem: "com.illinicover.app.v2", category: "api")
    private let baseURL: URL
    private let session: URLSession
    private let credentials: CredentialStore
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    private let generatedClient: any APIProtocol

    init(
        baseURL: URL,
        credentials: CredentialStore,
        session: URLSession = .shared,
        transport: (any ClientTransport)? = nil
    ) {
        self.baseURL = baseURL
        self.credentials = credentials
        self.session = session
        self.generatedClient = Client(
            serverURL: baseURL,
            configuration: .init(dateTranscoder: RFC3339DateTranscoder()),
            transport: transport ?? URLSessionTransport(configuration: .init(session: session)),
            middlewares: [CredentialMiddleware(credentials: credentials)]
        )

        let decoder = JSONDecoder()
        self.decoder = decoder
        self.encoder = JSONEncoder()
    }

    func status() async throws -> String {
        let output = try await invoke { try await generatedClient.getStatus() }
        switch output {
        case .ok(let response): return try response.body.json.status
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func createInstallation(requestID: String, installationToken: String) async throws -> String {
        let output = try await invoke {
            try await generatedClient.createInstallation(
                body: .json(.init(installationToken: installationToken, requestId: requestID))
            )
        }
        switch output {
        case .created(let response):
            let issued = try response.body.json
            guard requestIDsMatch(issued.requestId, requestID), issued.token == installationToken else {
                throw APIClientError.invalidResponse
            }
            return issued.token
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .tooManyRequests(let response): throw try server(response.body.json, status: 429)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func currentInstallationActorID() async throws -> String {
        let output = try await invoke {
            try await generatedClient.getCurrentInstallation()
        }
        switch output {
        case .ok(let response):
            return try response.body.json.actorId
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func rotateInstallation(
        requestID: String,
        replacementToken: String,
        authorizationToken: String
    ) async throws -> String {
        let output = try await invoke {
            try await generatedClient.rotateInstallation(
                headers: .init(xInstallationToken: authorizationToken),
                body: .json(.init(
                    replacementInstallationToken: replacementToken,
                    requestId: requestID
                ))
            )
        }
        switch output {
        case .created(let response):
            let issued = try response.body.json
            guard requestIDsMatch(issued.requestId, requestID), issued.token == replacementToken else {
                throw APIClientError.invalidResponse
            }
            return issued.token
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .unprocessableContent(let response): throw try server(response.body.json, status: 422)
        case .tooManyRequests(let response): throw try server(response.body.json, status: 429)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func coverBoard(eTag: String?) async throws -> HTTPResult<CoverBoardResponse> {
        let output = try await invoke {
            try await generatedClient.getCoverBoard(headers: .init(ifNoneMatch: eTag))
        }
        switch output {
        case .ok(let response):
            let board = try response.body.json
            return HTTPResult(
                value: CoverBoardResponse(
                    serviceDate: board.serviceDate,
                    generatedAt: board.generatedAt,
                    venues: board.venues.map(Self.mapCoverVenueCard)
                ),
                eTag: response.headers.eTag,
                notModified: false
            )
        case .notModified(let response):
            return HTTPResult(value: nil, eTag: response.headers.eTag ?? eTag, notModified: true)
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func venueCover(id: String) async throws -> VenueCoverResponse {
        let output = try await invoke {
            try await generatedClient.getVenueCover(path: .init(venue: id))
        }
        switch output {
        case .ok(let response):
            return Self.mapVenueCoverDetail(try response.body.json)
        case .notFound(let response): throw try server(response.body.json, status: 404)
        case .notModified: throw APIClientError.invalidResponse
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func coverHistory(venueID: String) async throws -> CoverHistoryResponse {
        let output = try await invoke {
            try await generatedClient.getVenueCoverHistory(path: .init(venue: venueID))
        }
        switch output {
        case .ok(let response):
            let value = try response.body.json
            return CoverHistoryResponse(
                venue: Self.mapVenue(value.venue),
                serviceDate: value.serviceDate,
                accessTier: CoverHistoryAccessTier(rawValue: value.accessTier.rawValue) ?? .limited,
                windowStart: value.windowStart,
                hasMore: value.hasMore,
                reports: value.reports.map(Self.mapRecentCoverReport)
            )
        case .notFound(let response): throw try server(response.body.json, status: 404)
        case .notModified: throw APIClientError.invalidResponse
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func timeMachine(venueID: String, target: Date) async throws -> TimeMachineResponse {
        let output = try await invoke {
            try await generatedClient.getVenueCoverTimeMachine(
                path: .init(venue: venueID),
                query: .init(targetTime: target)
            )
        }
        switch output {
        case .ok(let response):
            let value = try response.body.json
            return TimeMachineResponse(
                venue: Self.mapVenue(value.venue),
                targetTime: value.targetTime,
                knowledgeCutoff: value.knowledgeCutoff,
                mode: TimeMachineMode(rawValue: value.mode.rawValue) ?? .current,
                cover: value.cover.map { Self.mapCoverState($0.value1) } ?? Self.unavailableCover
            )
        case .forbidden(let response): throw try server(response.body.json, status: 403)
        case .notFound(let response): throw try server(response.body.json, status: 404)
        case .unprocessableContent(let response): throw try server(response.body.json, status: 422)
        case .tooManyRequests(let response): throw try server(response.body.json, status: 429)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func submitCover(_ value: CoverSubmissionRequest) async throws -> SubmissionReceipt {
        let body = try transcode(value, to: Components.Schemas.CoverSubmissionSchema.self)
        let output = try await invoke {
            try await generatedClient.createCoverSubmission(body: .json(body))
        }
        switch output {
        case .created(let response): return try transcode(response.body.json, to: SubmissionReceipt.self)
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .unprocessableContent(let response): throw try server(response.body.json, status: 422)
        case .tooManyRequests(let response): throw try server(response.body.json, status: 429)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func deals(eTag: String?) async throws -> HTTPResult<DealsResponse> {
        let output = try await invoke {
            try await generatedClient.getDealSlate(headers: .init(ifNoneMatch: eTag))
        }
        switch output {
        case .ok(let response):
            return HTTPResult(
                value: try transcode(response.body.json, to: DealsResponse.self),
                eTag: response.headers.eTag,
                notModified: false
            )
        case .notModified(let response):
            return HTTPResult(value: nil, eTag: response.headers.eTag ?? eTag, notModified: true)
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func venueDeals(venueID: String, eTag: String?) async throws -> HTTPResult<VenueDeals> {
        let output = try await invoke {
            try await generatedClient.getVenueDeals(
                path: .init(venue: venueID),
                headers: .init(ifNoneMatch: eTag)
            )
        }
        switch output {
        case .ok(let response):
            return HTTPResult(
                value: try transcode(response.body.json, to: VenueDeals.self),
                eTag: response.headers.eTag,
                notModified: false
            )
        case .notModified(let response):
            return HTTPResult(value: nil, eTag: response.headers.eTag ?? eTag, notModified: true)
        case .notFound(let response):
            throw try server(response.body.json, status: 404)
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func dealSuggestions(query: String, venueID: String?) async throws -> [DealSuggestion] {
        let output = try await invoke {
            try await generatedClient.searchDealSuggestions(
                query: .init(q: query.nilIfEmpty, venue: venueID, limit: 6)
            )
        }
        switch output {
        case .ok(let response):
            return try response.body.json.suggestions.map(Self.mapSuggestion)
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func submitDeal(_ value: DealEvidenceRequest) async throws -> SubmissionReceipt {
        let body = Components.Schemas.DealEvidenceInputSchema(
            action: .init(rawValue: value.action.rawValue)!,
            clientPlatform: value.clientPlatform.nilIfEmpty,
            clientVersion: value.clientVersion.nilIfEmpty,
            entryPoint: value.entryPoint.nilIfEmpty,
            location: value.location.map {
                .init(value1: .init(
                    accuracyMeters: $0.accuracyMeters,
                    latitude: $0.latitude,
                    longitude: $0.longitude,
                    permission: $0.permission.nilIfEmpty
                ))
            },
            observedAt: value.observedAt,
            serviceDateLocal: value.serviceDateLocal,
            submissionId: value.submissionId,
            submittedDealShape: value.submittedDeal.map { .init(value1: Self.generatedDealShape($0)) },
            supersedesEventId: value.supersedesEventId,
            targetDealId: value.targetDealId,
            targetLocalDatetime: value.targetLocalDateTime,
            targetPredictionId: value.targetPredictionId,
            vantagePoint: .init(rawValue: value.vantagePoint.rawValue),
            venueId: value.venueId
        )
        let output = try await invoke {
            try await generatedClient.createDealEvidence(body: .json(body))
        }
        switch output {
        case .created(let response):
            let receipt = try response.body.json
            return SubmissionReceipt(
                submissionId: receipt.submissionId,
                acceptedAt: receipt.acceptedAt,
                requestId: nil
            )
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .unprocessableContent(let response): throw try server(response.body.json, status: 422)
        case .tooManyRequests(let response): throw try server(response.body.json, status: 429)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func handbook(eTag: String?) async throws -> HTTPResult<[HandbookPageSummary]> {
        let output = try await invoke {
            try await generatedClient.getHandbook(headers: .init(ifNoneMatch: eTag))
        }
        switch output {
        case .ok(let response):
            let wire: HandbookListWire = try transcode(response.body.json, to: HandbookListWire.self)
            return HTTPResult(value: wire.pages, eTag: response.headers.eTag, notModified: false)
        case .notModified(let response):
            return HTTPResult(value: nil, eTag: response.headers.eTag ?? eTag, notModified: true)
        case .undocumented(let status, _):
            throw undocumented(status)
        }
    }

    func handbookPage(slug: String) async throws -> HandbookPage {
        let output = try await invoke {
            try await generatedClient.getHandbookPage(path: .init(slug: slug))
        }
        switch output {
        case .ok(let response): return try transcode(response.body.json, to: HandbookPage.self)
        case .notFound(let response): throw try server(response.body.json, status: 404)
        case .notModified: throw APIClientError.invalidResponse
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func requestEmailCode(email: String, intent: EmailCodeIntent) async throws -> EmailCodeChallenge {
        struct Body: Encodable, Sendable { let email: String }
        let path = intent == .signIn ? "/_allauth/app/v1/auth/code/request" : "/_allauth/app/v1/auth/signup"
        let request = try await makeJSONRequest(path, method: "POST", body: Body(email: email))
        let (data, response) = try await perform(request)
        // allauth deliberately returns 401 while the login-by-code flow is
        // pending. It is protocol state, not an authentication failure.
        guard response.statusCode == 200 || response.statusCode == 401 else {
            try validate(response, data: data)
            throw APIClientError.invalidResponse
        }
        guard let envelope = try? decoder.decode(AllauthEnvelope.self, from: data),
              let token = envelope.meta.sessionToken,
              envelope.data?.flows?.contains(where: {
                  let expected = intent == .signIn ? "login_by_code" : "verify_email"
                  return $0.id == expected && $0.isPending
              }) == true
        else { throw APIClientError.invalidResponse }
        try await credentials.writeRequired(token, for: .emailChallengeToken)
        return EmailCodeChallenge(sessionToken: token, intent: intent)
    }

    func resendEmailCode(intent: EmailCodeIntent) async throws {
        let path = intent == .signIn
            ? "/_allauth/app/v1/auth/code/resend"
            : "/_allauth/app/v1/auth/email/verify/resend"
        var request = try await makeRequest(path, method: "POST")
        guard let challengeToken = try await credentials.readRequired(.emailChallengeToken) else {
            throw APIClientError.unauthorized
        }
        request.setValue(challengeToken, forHTTPHeaderField: "X-Session-Token")
        let (data, response) = try await perform(request)
        try await persistReplacementChallengeToken(from: data)
        try validate(response, data: data)
    }

    func verifyEmailCode(code: String, intent: EmailCodeIntent) async throws -> AuthSessionResponse {
        struct LoginBody: Encodable, Sendable { let code: String }
        struct SignupBody: Encodable, Sendable { let key: String }
        var request: URLRequest
        switch intent {
        case .signIn:
            request = try await makeJSONRequest("/_allauth/app/v1/auth/code/confirm", method: "POST", body: LoginBody(code: code))
        case .signUp:
            request = try await makeJSONRequest("/_allauth/app/v1/auth/email/verify", method: "POST", body: SignupBody(key: code))
        }
        guard let challengeToken = try await credentials.readRequired(.emailChallengeToken) else {
            throw APIClientError.unauthorized
        }
        request.setValue(challengeToken, forHTTPHeaderField: "X-Session-Token")
        let (data, response) = try await perform(request)
        try await persistReplacementChallengeToken(from: data)
        try validate(response, data: data)
        let envelope = try decoder.decode(AllauthEnvelope.self, from: data)
        guard envelope.meta.isAuthenticated,
              let token = envelope.meta.sessionToken,
              let user = envelope.data?.user
        else { throw APIClientError.invalidResponse }
        try await credentials.writeRequired(token, for: .sessionToken)
        try await credentials.deleteRequired(.emailChallengeToken)
        let account = AccountSummary(id: user.id, email: user.email, firstName: user.displayName, graduationYear: nil)
        return AuthSessionResponse(account: account, sessionToken: token)
    }

    private func persistReplacementChallengeToken(from data: Data) async throws {
        guard let envelope = try? decoder.decode(AllauthEnvelope.self, from: data),
              let replacement = envelope.meta.sessionToken
        else { return }
        try await credentials.writeRequired(replacement, for: .emailChallengeToken)
    }

    func signOut() async throws {
        let request = try await makeRequest("/_allauth/app/v1/auth/session", method: "DELETE")
        let (data, response) = try await perform(request)
        // django-allauth revokes the token before its response reaches the
        // client, so a final 401 is a successful sign-out outcome.
        guard [200, 204, 401, 410].contains(response.statusCode) else {
            try validate(response, data: data)
            throw APIClientError.invalidResponse
        }
        try await credentials.deleteRequired(.sessionToken)
        try await credentials.deleteRequired(.emailChallengeToken)
    }

    func deleteAccount(requestID: String) async throws {
        let output = try await invoke {
            try await generatedClient.deleteCurrentAccount(
                body: .json(.init(requestId: requestID))
            )
        }
        switch output {
        case .ok(let response):
            let receipt = try response.body.json
            guard requestIDsMatch(receipt.requestId, requestID), receipt.deleted else {
                throw APIClientError.invalidResponse
            }
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func accountDeletionCompleted(requestID: String) async throws -> Bool {
        let output = try await invoke {
            try await generatedClient.getAccountDeletionStatus(path: .init(requestId: requestID))
        }
        switch output {
        case .ok(let response):
            let receipt = try response.body.json
            guard requestIDsMatch(receipt.requestId, requestID) else { throw APIClientError.invalidResponse }
            return receipt.deleted
        case .notFound: return false
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func linkInstallation(requestID: String) async throws {
        guard let token = try await credentials.readRequired(.installationToken) else { throw APIClientError.unauthorized }
        let output = try await invoke {
            try await generatedClient.linkCurrentInstallation(
                body: .json(.init(installationToken: token, requestId: requestID))
            )
        }
        switch output {
        case .ok(let response):
            let linked = try response.body.json
            guard requestIDsMatch(linked.requestId, requestID) else { throw APIClientError.invalidResponse }
            return
        case .conflict(let response): throw try server(response.body.json, status: 409)
        case .unprocessableContent(let response): throw try server(response.body.json, status: 422)
        case .undocumented(let status, _): throw undocumented(status)
        }
    }

    func me() async throws -> AccountSummary {
        let output = try await invoke { try await generatedClient.getCurrentAccount() }
        guard case .ok(let response) = output else { throw failure(for: output) }
        let account = try response.body.json
        return AccountSummary(
            id: account.id,
            email: account.email,
            firstName: account.displayName.nilIfEmpty,
            graduationYear: nil
        )
    }

    func entitlements() async throws -> EntitlementSummary {
        let output = try await invoke { try await generatedClient.getCurrentEntitlements() }
        guard case .ok(let response) = output else { throw failure(for: output) }
        return try transcode(response.body.json, to: EntitlementSummary.self)
    }

    func sendOutbox(kind: OutboxKind, payload: Data) async throws {
        switch kind {
        case .cover:
            _ = try await submitCover(decoder.decode(CoverSubmissionRequest.self, from: payload))
        case .deal:
            _ = try await submitDeal(decoder.decode(DealEvidenceRequest.self, from: payload))
        }
    }

    private func invoke<Value: Sendable>(
        _ operation: @Sendable () async throws -> Value
    ) async throws -> Value {
        do {
            return try await operation()
        } catch let error as APIClientError {
            throw error
        } catch let error as ClientError {
            // Never surface ClientError descriptions: they may contain an
            // encoded request body with an exact location observation.
            if error.response == nil {
                logger.notice("Generated API request failed before receiving a response")
                throw APIClientError.transport("network")
            }
            logger.error("Generated API response could not be decoded")
            throw APIClientError.invalidResponse
        } catch {
            logger.error("Generated API request failed with a non-client error")
            throw APIClientError.invalidResponse
        }
    }

    private func transcode<Source: Encodable, Destination: Decodable>(
        _ source: Source,
        to destination: Destination.Type
    ) throws -> Destination {
        try decoder.decode(destination, from: encoder.encode(source))
    }

    private func server(_ schema: Components.Schemas.ErrorSchema, status: Int) throws -> APIClientError {
        APIClientError.server(
            APIErrorPayload(code: schema.code, message: schema.message, requestId: schema.requestId),
            status: status
        )
    }

    private func undocumented(_ status: Int) -> APIClientError {
        if status == 401 { return .unauthorized }
        return .server(
            APIErrorPayload(
                code: "http_\(status)",
                message: "The server could not complete this request.",
                requestId: nil
            ),
            status: status
        )
    }

    /// Django serializes UUIDs in lowercase while Foundation's `UUID` string
    /// form is uppercase. Compare UUID identity, not presentation, or a
    /// successful idempotent identity write is mistaken for a malformed
    /// response and immediately retried.
    private func requestIDsMatch(_ response: String, _ request: String) -> Bool {
        guard let responseID = UUID(uuidString: response), let requestID = UUID(uuidString: request) else {
            return response == request
        }
        return responseID == requestID
    }

    private func failure(for output: Operations.GetCurrentAccount.Output) -> APIClientError {
        guard case .undocumented(let status, _) = output else { return .invalidResponse }
        return undocumented(status)
    }

    private func failure(for output: Operations.GetCurrentEntitlements.Output) -> APIClientError {
        guard case .undocumented(let status, _) = output else { return .invalidResponse }
        return undocumented(status)
    }

    /// Generated response types are the wire authority. Map them explicitly
    /// instead of serializing them back through JSON: nullable OpenAPI wrapper
    /// types and date transcoders are transport details, not domain Codable
    /// shapes.
    private static func mapVenue(_ value: Components.Schemas.VenueSummarySchema) -> Venue {
        Venue(
            id: value.id,
            slug: value.slug,
            name: value.name,
            address: value.address.nilIfEmpty,
            openedYear: value.openedYear
        )
    }

    private static let unavailableCover = CoverDecision(
        price: .unavailable,
        source: .unavailable,
        freshnessSeconds: nil,
        decisionId: nil,
        status: "unavailable"
    )

    private static func mapCoverPrice(_ value: Components.Schemas.CoverPriceSchema) -> CoverPrice {
        switch value.kind {
        case "single":
            return value.amountCents.map(CoverPrice.single) ?? .unavailable
        case "range":
            guard let low = value.lowCents, let high = value.highCents else { return .unavailable }
            return .range(low, high)
        default:
            return .unavailable
        }
    }

    private static func mapCoverState(_ value: Components.Schemas.CoverStateSchema) -> CoverDecision {
        CoverDecision(
            price: mapCoverPrice(value.price),
            source: CoverSource(rawValue: value.source) ?? .unavailable,
            freshnessSeconds: value.freshnessSeconds,
            decisionId: value.decisionId,
            status: value.status
        )
    }

    private static func mapVibes(_ value: Components.Schemas.VibeSummarySchema) -> VibeSummary {
        VibeSummary(
            lineLength: value.lineLength,
            lineSpeed: value.lineSpeed,
            crowdLevel: value.crowdLevel
        )
    }

    private static func mapCoverVenueCard(_ value: Components.Schemas.CoverVenueCardSchema) -> CoverVenueCard {
        CoverVenueCard(
            venue: mapVenue(value.venue),
            cover: value.cover.map { mapCoverState($0.value1) } ?? unavailableCover,
            recentReportCount: value.recentReportCount,
            latestActivityAt: value.latestActivityAt,
            vibes: mapVibes(value.vibes)
        )
    }

    private static func mapRecentCoverReport(_ value: Components.Schemas.RecentReportSchema) -> RecentCoverReport {
        RecentCoverReport(
            id: value.submissionId,
            price: value.priceCents.map(CoverPrice.single),
            observedAt: value.observedAt,
            sourceLabel: value.interaction
                .replacingOccurrences(of: "_", with: " ")
                .capitalized,
            locationContext: value.broadContext,
            vibes: value.vibes
        )
    }

    private static func mapVenueDeal(_ value: Components.Schemas.VenueDealSummarySchema) -> Deal {
        let price: DealPrice
        switch value.priceKind {
        case "absolute", "single":
            price = value.priceCents.map(DealPrice.single) ?? .unknown
        case "range":
            if let low = value.priceLowCents, let high = value.priceHighCents {
                price = .range(low, high)
            } else {
                price = .unknown
            }
        case "relative", "percent_off":
            price = value.discountPercent.map { .percentOff(Int($0.rounded())) } ?? .unknown
        default:
            price = .unknown
        }
        return Deal(
            id: value.id,
            familyId: nil,
            predictionId: value.predictionId,
            category: DealCategory(rawValue: value.category) ?? .drink,
            name: value.displayName,
            price: price,
            servingFormat: value.servingFormat.nilIfEmpty,
            unit: value.unit.nilIfEmpty,
            timing: .flattened(
                description: value.timingDescription,
                known: value.timingKnown,
                whileSuppliesLast: value.whileSuppliesLast
            ),
            status: value.status
        )
    }

    private static func mapVenueCoverDetail(
        _ value: Components.Schemas.VenueCoverDetailSchema
    ) -> VenueCoverResponse {
        VenueCoverResponse(
            venue: mapVenue(value.venue),
            cover: value.cover.map { mapCoverState($0.value1) } ?? unavailableCover,
            recentReports: value.recentReports.map(mapRecentCoverReport),
            vibes: mapVibes(value.vibes),
            deals: value.deals.map(mapVenueDeal)
        )
    }

    private static func mapSuggestion(_ value: Components.Schemas.DealSuggestionSchema) -> DealSuggestion {
        let price: DealPrice
        switch value.priceKind {
        case "absolute", "single": price = value.priceCents.map(DealPrice.single) ?? .unknown
        case "range":
            if let low = value.priceLowCents, let high = value.priceHighCents {
                price = .range(low, high)
            } else {
                price = .unknown
            }
        case "relative", "percent_off": price = value.discountPercent.map { .percentOff(Int($0.rounded())) } ?? .unknown
        default: price = .unknown
        }
        let timing = DealTiming.flattened(
            description: value.timingDescription,
            known: value.timingKnown,
            whileSuppliesLast: value.whileSuppliesLast
        )
        let identity = [
            value.canonicalFamilyId,
            value.category,
            value.displayName,
            value.servingFormat,
            value.unit,
            value.priceKind,
            value.priceCents.map { String($0) } ?? "",
            value.priceLowCents.map { String($0) } ?? "",
            value.priceHighCents.map { String($0) } ?? "",
            value.discountPercent.map { String($0) } ?? "",
            timing.identityComponent,
        ].joined(separator: ":")
        return DealSuggestion(
            deal: Deal(
                id: "suggestion:\(identity)",
                familyId: value.canonicalFamilyId,
                category: DealCategory(rawValue: value.category) ?? .drink,
                name: value.displayName,
                price: price,
                servingFormat: value.servingFormat.nilIfEmpty,
                unit: value.unit.nilIfEmpty,
                timing: timing,
                status: "current",
                evidenceEventId: nil
            ),
            sourceScope: value.sourceScope,
            lastSeenServiceDateLocal: value.lastSeenServiceDateLocal,
            matchedSource: value.matchedSource.flatMap { DealSuggestionMatchSource(rawValue: $0.rawValue) },
            matchedText: value.matchedText
        )
    }

    private static func generatedDealShape(
        _ value: SubmittedDealShape
    ) -> Components.Schemas.DealShapeSchema {
        let priceKind: Components.Schemas.DealShapeSchema.PriceKindPayload
        let priceCents: Int?
        let priceLowCents: Int?
        let priceHighCents: Int?
        let discountPercent: Double?
        switch value.price {
        case .single(let cents):
            priceKind = .absolute
            priceCents = cents
            priceLowCents = nil
            priceHighCents = nil
            discountPercent = nil
        case .range(let low, let high):
            priceKind = .range
            priceCents = nil
            priceLowCents = low
            priceHighCents = high
            discountPercent = nil
        case .percentOff(let percent):
            priceKind = .relative
            priceCents = nil
            priceLowCents = nil
            priceHighCents = nil
            discountPercent = Double(percent)
        case .unknown:
            priceKind = .unknown
            priceCents = nil
            priceLowCents = nil
            priceHighCents = nil
            discountPercent = nil
        }

        let timingDescription: String?
        let timingKnown: Bool
        let whileSuppliesLast: Bool
        switch value.timing {
        case .allNight:
            timingDescription = "All night"; timingKnown = true; whileSuppliesLast = false
        case .untilSoldOut:
            timingDescription = nil; timingKnown = true; whileSuppliesLast = true
        case .unknown:
            timingDescription = nil; timingKnown = false; whileSuppliesLast = false
        case .before(let time):
            timingDescription = "Before \(time)"; timingKnown = true; whileSuppliesLast = false
        case .after(let time):
            timingDescription = "After \(time)"; timingKnown = true; whileSuppliesLast = false
        case .between(let start, let end):
            timingDescription = "\(start)–\(end)"; timingKnown = true; whileSuppliesLast = false
        }

        return .init(
            canonicalFamilyId: value.canonicalFamilyId,
            category: .init(rawValue: value.category.rawValue)!,
            discountPercent: discountPercent,
            displayName: value.name,
            priceCents: priceCents,
            priceHighCents: priceHighCents,
            priceKind: priceKind,
            priceLowCents: priceLowCents,
            servingFormat: value.servingFormat,
            timingDescription: timingDescription,
            timingKnown: timingKnown,
            unit: value.unit,
            whileSuppliesLast: whileSuppliesLast
        )
    }

    private func makeJSONRequest<Body: Encodable & Sendable>(_ path: String, method: String, body: Body?) async throws -> URLRequest {
        var request = try await makeRequest(path, method: method)
        if let body {
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func makeRequest(_ path: String, method: String, query: [URLQueryItem] = []) async throws -> URLRequest {
        guard var components = URLComponents(url: baseURL.appending(path: path), resolvingAgainstBaseURL: false) else {
            throw APIClientError.invalidConfiguration
        }
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw APIClientError.invalidConfiguration }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        if let token = try await credentials.readRequired(.sessionToken) {
            request.setValue(token, forHTTPHeaderField: "X-Session-Token")
        }
        if let installation = try await credentials.readRequired(.installationToken) {
            request.setValue(installation, forHTTPHeaderField: "X-Installation-Token")
        }
        return request
    }

    private func perform(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        do {
            let (data, response) = try await session.data(for: request)
            guard let response = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
            return (data, response)
        } catch let error as APIClientError {
            throw error
        } catch {
            throw APIClientError.transport("network")
        }
    }

    private func validate(_ response: HTTPURLResponse, data: Data) throws {
        if response.statusCode == 401 { throw APIClientError.unauthorized }
        guard (200..<300).contains(response.statusCode) else {
            let payload = (try? decoder.decode(APIErrorPayload.self, from: data))
                ?? APIErrorPayload(code: "http_\(response.statusCode)", message: "The server could not complete this request.", requestId: nil)
            throw APIClientError.server(payload, status: response.statusCode)
        }
    }
}

private struct CoverHistoryWire: Decodable { let reports: [RecentCoverReport] }
private struct HandbookListWire: Decodable { let pages: [HandbookPageSummary] }

private struct CredentialMiddleware: ClientMiddleware {
    let credentials: CredentialStore

    func intercept(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String,
        next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        request.headerFields[.xRequestID] = UUID().uuidString
        if let session = try await credentials.readRequired(.sessionToken) {
            request.headerFields[.xSessionToken] = session
        }
        if request.headerFields[.xInstallationToken] == nil,
           let installation = try await credentials.readRequired(.installationToken) {
            request.headerFields[.xInstallationToken] = installation
        }
        return try await next(request, body, baseURL)
    }
}

private extension HTTPField.Name {
    static let xRequestID = Self("X-Request-ID")!
    static let xSessionToken = Self("X-Session-Token")!
    static let xInstallationToken = Self("X-Installation-Token")!
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

private struct AllauthEnvelope: Decodable {
    struct Meta: Decodable {
        let isAuthenticated: Bool
        let sessionToken: String?
        enum CodingKeys: String, CodingKey { case isAuthenticated = "is_authenticated", sessionToken = "session_token" }
    }
    struct DataPayload: Decodable {
        struct Flow: Decodable {
            let id: String
            let isPending: Bool
            enum CodingKeys: String, CodingKey { case id, isPending = "is_pending" }
        }
        struct User: Decodable {
            let id: String
            let email: String
            let displayName: String?
            enum CodingKeys: String, CodingKey { case id, email, displayName = "display" }
        }
        let flows: [Flow]?
        let user: User?
    }
    let data: DataPayload?
    let meta: Meta
}

private enum ISO8601Wire {
    static func string(from date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    static func date(from value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
}
