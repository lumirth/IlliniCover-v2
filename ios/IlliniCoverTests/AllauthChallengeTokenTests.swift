import Foundation
import Testing
@testable import IlliniCover

@Suite("Allauth challenge token rotation", .serialized)
struct AllauthChallengeTokenTests {
    @Test("Resend persists the replacement challenge token")
    func resendPersistsReplacementToken() async throws {
        let credentials = CredentialStore(
            service: "com.illinicover.tests.allauth-resend.\(UUID().uuidString)"
        )
        try await credentials.writeRequired("old-challenge-token", for: .emailChallengeToken)
        let session = challengeSession(
            status: 200,
            body: challengeEnvelope(token: "resend-replacement-token")
        )
        let client = LiveAPIClient(
            baseURL: URL(string: "https://allauth.invalid")!,
            credentials: credentials,
            session: session
        )

        try await client.resendEmailCode(intent: .signIn)

        #expect(try await credentials.readRequired(.emailChallengeToken) == "resend-replacement-token")
        #expect(AllauthChallengeURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Session-Token") == "old-challenge-token")
        try await credentials.deleteAllRequired()
        session.invalidateAndCancel()
        AllauthChallengeURLProtocol.reset()
    }

    @Test("Invalid verification persists the replacement challenge token before throwing")
    func invalidVerificationPersistsReplacementToken() async throws {
        let credentials = CredentialStore(
            service: "com.illinicover.tests.allauth-invalid.\(UUID().uuidString)"
        )
        try await credentials.writeRequired("old-challenge-token", for: .emailChallengeToken)
        let session = challengeSession(
            status: 400,
            body: challengeEnvelope(token: "verify-replacement-token")
        )
        let client = LiveAPIClient(
            baseURL: URL(string: "https://allauth.invalid")!,
            credentials: credentials,
            session: session
        )

        do {
            _ = try await client.verifyEmailCode(code: "WRNG-CODE", intent: .signIn)
            Issue.record("Expected invalid verification to fail")
        } catch {
            #expect(error is APIClientError)
        }

        #expect(try await credentials.readRequired(.emailChallengeToken) == "verify-replacement-token")
        #expect(await credentials.read(.sessionToken) == nil)
        #expect(AllauthChallengeURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Session-Token") == "old-challenge-token")
        try await credentials.deleteAllRequired()
        session.invalidateAndCancel()
        AllauthChallengeURLProtocol.reset()
    }

    private func challengeSession(status: Int, body: String) -> URLSession {
        AllauthChallengeURLProtocol.configure(status: status, body: body)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AllauthChallengeURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func challengeEnvelope(token: String) -> String {
        """
        {"data":{"flows":[{"id":"login_by_code","is_pending":true}]},"meta":{"is_authenticated":false,"session_token":"\(token)"}}
        """
    }
}

private final class AllauthChallengeURLProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) private static var responseStatus = 200
    nonisolated(unsafe) private static var responseBody = ""
    nonisolated(unsafe) private(set) static var lastRequest: URLRequest?

    static func configure(status: Int, body: String) {
        responseStatus = status
        responseBody = body
        lastRequest = nil
    }

    static func reset() {
        responseStatus = 200
        responseBody = ""
        lastRequest = nil
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lastRequest = request
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: Self.responseStatus,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(Self.responseBody.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
