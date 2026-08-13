import Foundation
import Security
import Testing
@testable import IlliniCover

@Suite("Keychain credentials", .serialized)
struct CredentialStoreTests {
    @Test("Bearer credentials round trip only through Keychain")
    func roundTrip() async {
        let store = CredentialStore(service: "com.illinicover.tests.\(UUID().uuidString)")
        await store.write("secret-value", for: .sessionToken)
        let stored = await store.read(.sessionToken)
        #expect(stored == "secret-value")
        await store.delete(.sessionToken)
        let deleted = await store.read(.sessionToken)
        #expect(deleted == nil)
    }

    @Test("Required Keychain operations surface unexpected OSStatus failures")
    func requiredOperationsFailClosed() async throws {
        let service = "com.illinicover.tests.keychain-failure.\(UUID().uuidString)"
        let seed = CredentialStore(service: service)
        try await seed.writeRequired("session-secret", for: .sessionToken)
        let failing = CredentialStore(service: service) { operation, key in
            operation == .delete && key == .sessionToken ? errSecInteractionNotAllowed : nil
        }

        await #expect(throws: CredentialStoreError.self) {
            try await failing.deleteRequired(.sessionToken)
        }
        #expect(try await seed.readRequired(.sessionToken) == "session-secret")

        try await seed.deleteRequired(.sessionToken)
    }

    @Test("Required bulk deletion surfaces a failure and preserves the failed credential")
    func requiredBulkDeleteFailsClosed() async throws {
        let service = "com.illinicover.tests.keychain-bulk-failure.\(UUID().uuidString)"
        let seed = CredentialStore(service: service)
        try await seed.writeRequired("installation-secret", for: .installationToken)
        try await seed.writeRequired("session-secret", for: .sessionToken)
        let failing = CredentialStore(service: service) { operation, key in
            operation == .delete && key == .sessionToken ? errSecInteractionNotAllowed : nil
        }

        await #expect(throws: CredentialStoreError.self) {
            try await failing.deleteAllRequired()
        }
        #expect(try await seed.readRequired(.sessionToken) == "session-secret")

        try await seed.deleteAllRequired()
    }

    @Test("Leaving sign-in abandons the pending email challenge")
    func signInCancellationClearsChallenge() async throws {
        let store = CredentialStore(service: "com.illinicover.tests.sign-in-cancel.\(UUID().uuidString)")
        try await store.writeRequired("pending-allauth-session", for: .emailChallengeToken)

        await SignInFlowLifecycle.abandonChallenge(in: store)

        #expect(try await store.readRequired(.emailChallengeToken) == nil)
    }
}
