import Foundation

enum APIClientError: LocalizedError, Equatable, Sendable {
    case offline, invalidResponse, unauthorized, server(String, Int)
    var errorDescription: String? {
        switch self {
        case .offline: "You appear to be offline."
        case .invalidResponse: "The server returned an unreadable response."
        case .unauthorized: "Please sign in again."
        case .server(let message, _): message
        }
    }
    var retryable: Bool {
        switch self { case .offline: true; case .server(_, let status): status == 408 || status == 429 || status >= 500; default: false }
    }
}

actor LiveAPIClient {
    private let baseURL: URL
    private let session: URLSession
    private let credentials: CredentialStore
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private let localDecoder = JSONDecoder()

    init(baseURL: URL, credentials: CredentialStore, session: URLSession = .shared) {
        self.baseURL = baseURL; self.credentials = credentials; self.session = session
        encoder.dateEncodingStrategy = .custom { date, encoder in var value = encoder.singleValueContainer(); try value.encode(ISO8601Wire.string(date)) }
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            guard let date = ISO8601Wire.date(value) else { throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid RFC3339 date") }
            return date
        }
    }

    func createInstallation(token: String) async throws {
        try await send("POST", "/api/installations", body: ["installationToken": token])
    }

    func rotateInstallation(oldToken: String, newToken: String) async throws {
        try await send("POST", "/api/installations/rotate", body: ["replacementInstallationToken": newToken], installation: oldToken)
    }

    func coverBoard() async throws -> CoverBoardResponse { try await get("/api/cover") }
    func venueCover(_ id: String) async throws -> VenueCoverResponse { try await get("/api/venues/\(id)/cover") }
    func coverHistory(_ id: String) async throws -> CoverHistoryResponse { try await get("/api/venues/\(id)/cover/history") }
    func deals() async throws -> DealsResponse { try await get("/api/deals") }
    func handbook() async throws -> [HandbookPageSummary] { try await get("/api/handbook", as: HandbookList.self).pages }
    func handbookPage(_ slug: String) async throws -> HandbookPage { try await get("/api/handbook/\(slug)") }
    func me() async throws -> AccountSummary { try await get("/api/me") }
    func entitlements() async throws -> EntitlementSummary { try await get("/api/me/entitlements") }

    func timeMachine(_ id: String, target: Date) async throws -> TimeMachineResponse {
        try await get("/api/venues/\(id)/cover/time-machine", query: [URLQueryItem(name: "targetTime", value: ISO8601Wire.string(target))])
    }

    func dealSuggestions(_ query: String, venueID: String) async throws -> [DealSuggestion] {
        try await get("/api/deal-suggestions", query: [
            URLQueryItem(name: "q", value: query.nilIfBlank), URLQueryItem(name: "venue", value: venueID), URLQueryItem(name: "limit", value: "8"),
        ], as: SuggestionList.self).suggestions
    }

    func submitCover(_ request: CoverSubmissionRequest) async throws { try await send("POST", "/api/cover-submissions", body: request) }
    func submitDeal(_ request: DealEvidenceRequest) async throws { try await send("POST", "/api/deal-evidence", body: request) }

    func linkInstallation() async throws {
        guard let token = try await credentials.read(.installationToken) else { throw APIClientError.unauthorized }
        try await send("POST", "/api/me/link-installation", body: ["installationToken": token])
    }

    func deleteAccount() async throws { try await send("DELETE", "/api/me") }

    func requestEmailCode(_ email: String, intent: EmailCodeIntent) async throws -> EmailCodeChallenge {
        let path = intent == .signIn ? "/_allauth/app/v1/auth/code/request" : "/_allauth/app/v1/auth/signup"
        let (data, response) = try await perform(try await request("POST", path, body: ["email": email]))
        let envelope = try await captureChallengeToken(data)
        guard [200, 401].contains(response.statusCode), envelope?.meta.sessionToken != nil else {
            try validate(response, data); throw APIClientError.invalidResponse
        }
        return .init(intent: intent)
    }

    func resendEmailCode(_ intent: EmailCodeIntent) async throws {
        let path = intent == .signIn ? "/_allauth/app/v1/auth/code/resend" : "/_allauth/app/v1/auth/email/verify/resend"
        let (data, response) = try await perform(try await challengeRequest(path, body: Empty()))
        _ = try await captureChallengeToken(data)
        try validate(response, data)
    }

    func verifyEmailCode(_ code: String, intent: EmailCodeIntent) async throws -> AuthSessionResponse {
        let path = intent == .signIn ? "/_allauth/app/v1/auth/code/confirm" : "/_allauth/app/v1/auth/email/verify"
        let key = intent == .signIn ? "code" : "key"
        let (data, response) = try await perform(try await challengeRequest(path, body: [key: code]))
        let envelope = try await captureChallengeToken(data)
        try validate(response, data)
        guard let envelope, envelope.meta.isAuthenticated == true, let token = envelope.meta.sessionToken, let user = envelope.data?.user else { throw APIClientError.invalidResponse }
        try await credentials.write(token, for: .sessionToken)
        try await credentials.delete(.emailChallengeToken)
        return .init(account: .init(displayName: user.displayName ?? "", email: user.email, id: user.id))
    }

    func signOut() async throws {
        let (data, response) = try await perform(try await request("DELETE", "/_allauth/app/v1/auth/session", body: Empty()))
        guard [200, 204, 401, 410].contains(response.statusCode) else { try validate(response, data); throw APIClientError.invalidResponse }
        try await credentials.delete(.sessionToken); try await credentials.delete(.emailChallengeToken)
    }

    func sendOutbox(_ entry: OutboxEntry) async throws {
        switch entry.kind {
        case .cover: try await submitCover(localDecoder.decode(CoverSubmissionRequest.self, from: entry.data))
        case .deal: try await submitDeal(localDecoder.decode(DealEvidenceRequest.self, from: entry.data))
        }
    }

    private func get<Value: Decodable>(_ path: String, query: [URLQueryItem] = [], as: Value.Type = Value.self) async throws -> Value {
        let (data, response) = try await perform(try await request("GET", path, query: query, body: Optional<Empty>.none))
        try validate(response, data)
        do { return try decoder.decode(Value.self, from: data) } catch { throw APIClientError.invalidResponse }
    }

    private func send<Body: Encodable>(_ method: String, _ path: String, body: Body, installation: String? = nil) async throws {
        var request = try await request(method, path, body: body)
        if let installation { request.setValue(installation, forHTTPHeaderField: "X-Installation-Token") }
        let (data, response) = try await perform(request)
        try validate(response, data)
    }

    private func send(_ method: String, _ path: String) async throws {
        let (data, response) = try await perform(try await request(method, path, body: Optional<Empty>.none))
        try validate(response, data)
    }

    private func request<Body: Encodable>(_ method: String, _ path: String, query: [URLQueryItem] = [], body: Body?) async throws -> URLRequest {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { throw APIClientError.invalidResponse }
        components.path = path; components.queryItems = query.isEmpty ? nil : query
        guard let url = components.url else { throw APIClientError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method; request.timeoutInterval = 15; request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body { request.httpBody = try encoder.encode(body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token = try await credentials.read(.sessionToken) { request.setValue(token, forHTTPHeaderField: "X-Session-Token") }
        if let token = try await credentials.read(.installationToken) { request.setValue(token, forHTTPHeaderField: "X-Installation-Token") }
        return request
    }

    private func challengeRequest<Body: Encodable>(_ path: String, body: Body) async throws -> URLRequest {
        var request = try await request("POST", path, body: body)
        guard let token = try await credentials.read(.emailChallengeToken) else { throw APIClientError.unauthorized }
        request.setValue(token, forHTTPHeaderField: "X-Session-Token")
        return request
    }

    private func captureChallengeToken(_ data: Data) async throws -> AllauthEnvelope? {
        guard let envelope = try? decoder.decode(AllauthEnvelope.self, from: data) else { return nil }
        if let token = envelope.meta.sessionToken { try await credentials.write(token, for: .emailChallengeToken) }
        return envelope
    }

    private func perform(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        do {
            let (data, response) = try await session.data(for: request)
            guard let response = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
            return (data, response)
        } catch let error as APIClientError { throw error }
        catch { throw APIClientError.offline }
    }

    private func validate(_ response: HTTPURLResponse, _ data: Data) throws {
        if response.statusCode == 401 { throw APIClientError.unauthorized }
        guard (200..<300).contains(response.statusCode) else {
            throw APIClientError.server((try? decoder.decode(APIError.self, from: data).message) ?? "The server could not complete this request.", response.statusCode)
        }
    }
}

private struct Empty: Codable {}
private struct APIError: Decodable { let message: String }
private struct HandbookList: Decodable { let pages: [HandbookPageSummary] }
private struct SuggestionList: Decodable { let suggestions: [DealSuggestion] }
private struct AllauthEnvelope: Decodable {
    struct Meta: Decodable {
        let isAuthenticated: Bool?; let sessionToken: String?
        enum CodingKeys: String, CodingKey { case isAuthenticated = "is_authenticated", sessionToken = "session_token" }
    }
    struct Payload: Decodable {
        struct User: Decodable {
            let id: String; let email: String; let displayName: String?
            enum CodingKeys: String, CodingKey { case id, email, displayName = "display" }
        }
        let user: User?
    }
    let data: Payload?; let meta: Meta
}

private enum ISO8601Wire {
    static func formatter(fractional: Bool) -> ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        if fractional { formatter.formatOptions.insert(.withFractionalSeconds) }
        return formatter
    }
    static func string(_ date: Date) -> String { formatter(fractional: true).string(from: date) }
    static func date(_ string: String) -> Date? {
        formatter(fractional: true).date(from: string) ?? formatter(fractional: false).date(from: string)
    }
}
