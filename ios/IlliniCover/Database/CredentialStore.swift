import Foundation
import Security

enum CredentialKey: String, CaseIterable, Sendable {
    case installationToken = "installation-token"
    case sessionToken = "session-token"
    case emailChallengeToken = "email-challenge-token"
}

actor CredentialStore {
    private let service: String
    init(service: String) { self.service = service }

    func read(_ key: CredentialKey) throws -> String? {
        var query = base(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            throw CredentialStoreError.keychain(status)
        }
        return value
    }

    func write(_ value: String, for key: CredentialKey) throws {
        guard let data = value.data(using: .utf8) else { throw CredentialStoreError.invalidValue }
        let query = base(key)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insertion = query
            insertion.merge(attributes) { _, new in new }
            let insertionStatus = SecItemAdd(insertion as CFDictionary, nil)
            guard insertionStatus == errSecSuccess else { throw CredentialStoreError.keychain(insertionStatus) }
        } else if status != errSecSuccess {
            throw CredentialStoreError.keychain(status)
        }
    }

    func delete(_ key: CredentialKey) throws {
        let status = SecItemDelete(base(key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw CredentialStoreError.keychain(status) }
    }

    func deleteAll() throws { for key in CredentialKey.allCases { try delete(key) } }

    static func makeInstallationToken() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw CredentialStoreError.randomnessUnavailable
        }
        return "ic_install_" + Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func base(_ key: CredentialKey) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key.rawValue]
    }
}

enum CredentialStoreError: Error { case randomnessUnavailable, invalidValue, keychain(OSStatus) }
