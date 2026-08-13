import Foundation
import Security

enum CredentialKey: String, Sendable {
    case installationToken = "installation-token"
    case pendingInstallationToken = "pending-installation-token"
    case sessionToken = "session-token"
    case emailChallengeToken = "email-challenge-token"
    case linkedAccountID = "linked-account-id"
    case accountLinkConflict = "account-link-conflict"
    case pendingDeletionAccountID = "pending-deletion-account-id"
}

enum CredentialOperation: Sendable { case read, write, delete }

actor CredentialStore {
    private static let allKeys: [CredentialKey] = [
        .installationToken,
        .pendingInstallationToken,
        .sessionToken,
        .emailChallengeToken,
        .linkedAccountID,
        .accountLinkConflict,
        .pendingDeletionAccountID,
    ]

    private let service: String
    private let statusOverride: @Sendable (CredentialOperation, CredentialKey) -> OSStatus?

    init(
        service: String,
        statusOverride: @escaping @Sendable (CredentialOperation, CredentialKey) -> OSStatus? = { _, _ in nil }
    ) {
        self.service = service
        self.statusOverride = statusOverride
    }

    func read(_ key: CredentialKey) -> String? {
        try? readRequired(key)
    }

    func readRequired(_ key: CredentialKey) throws -> String? {
        if let status = statusOverride(.read, key) {
            guard status == errSecItemNotFound else { throw CredentialStoreError.keychain(status) }
            return nil
        }
        var query = baseQuery(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw CredentialStoreError.keychain(status) }
        guard let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            throw CredentialStoreError.invalidStoredValue
        }
        return value
    }

    func write(_ value: String, for key: CredentialKey) {
        try? writeRequired(value, for: key)
    }

    func writeRequired(_ value: String, for key: CredentialKey) throws {
        if let status = statusOverride(.write, key), status != errSecSuccess {
            throw CredentialStoreError.keychain(status)
        }
        guard let data = value.data(using: .utf8) else { throw CredentialStoreError.invalidStoredValue }
        let query = baseQuery(key)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insertion = query
            insertion.merge(attributes) { _, new in new }
            let addStatus = SecItemAdd(insertion as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw CredentialStoreError.keychain(addStatus) }
        } else if status != errSecSuccess {
            throw CredentialStoreError.keychain(status)
        }
    }

    func delete(_ key: CredentialKey) {
        try? deleteRequired(key)
    }

    func deleteRequired(_ key: CredentialKey) throws {
        let status = statusOverride(.delete, key) ?? SecItemDelete(baseQuery(key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialStoreError.keychain(status)
        }
    }

    func deleteAll() {
        for key in Self.allKeys {
            delete(key)
        }
    }

    /// Destructive/privacy-sensitive flows must use this variant. An
    /// unexpected Keychain failure leaves their persisted recovery marker in
    /// place instead of presenting product data with credentials whose erasure
    /// was never confirmed.
    func deleteAllRequired() throws {
        for key in Self.allKeys {
            try deleteRequired(key)
        }
    }

    static func makeInstallationToken() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw CredentialStoreError.randomnessUnavailable
        }
        let value = Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return "ic_install_\(value)"
    }

    private func baseQuery(_ key: CredentialKey) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key.rawValue,
        ]
    }
}

enum CredentialStoreError: Error {
    case randomnessUnavailable
    case invalidStoredValue
    case keychain(OSStatus)
}
