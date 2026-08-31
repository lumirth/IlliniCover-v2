import Foundation
import Observation
import RevenueCat

@MainActor @Observable
final class BillingModel {
    private let apiKey: String?
    private var accountID: String?
    var packages: [RevenueCat.Package] = []
    var clientPremium = false
    var isLoading = false
    var errorMessage: String?

    init(apiKey: String?) { self.apiKey = apiKey }

    func configure(for accountID: String) async {
        guard let apiKey else { errorMessage = "Purchases are not configured in this build."; return }
        do {
            if !Purchases.isConfigured { Purchases.configure(withAPIKey: apiKey, appUserID: accountID) }
            else if self.accountID != accountID { _ = try await Purchases.shared.logIn(accountID) }
            self.accountID = accountID
            try await refresh()
        } catch { errorMessage = error.localizedDescription }
    }

    func refresh() async throws {
        guard accountID != nil else { return }
        isLoading = true; defer { isLoading = false }
        packages = try await Purchases.shared.offerings().current?.availablePackages ?? []
        apply(try await Purchases.shared.customerInfo())
    }

    func purchase(_ package: RevenueCat.Package) async throws -> Bool {
        guard accountID != nil else { throw BillingError.signInRequired }
        guard !clientPremium else { throw BillingError.confirmationPending }
        isLoading = true; defer { isLoading = false }
        let result = try await Purchases.shared.purchase(package: package)
        apply(result.customerInfo)
        return !result.userCancelled
    }

    func restore() async throws -> Bool {
        guard accountID != nil else { throw BillingError.signInRequired }
        isLoading = true; defer { isLoading = false }
        apply(try await Purchases.shared.restorePurchases())
        return clientPremium
    }

    func disable() { packages = []; clientPremium = false; errorMessage = nil }

    func retire() async {
        disable()
        if Purchases.isConfigured { _ = try? await Purchases.shared.logOut() }
        accountID = nil
    }

    private func apply(_ info: RevenueCat.CustomerInfo) {
        clientPremium = info.entitlements["premium"]?.isActive == true
    }
}

enum BillingError: LocalizedError, Equatable {
    case signInRequired, confirmationPending
    var errorDescription: String? {
        self == .signInRequired ? "Sign in to continue." : "Apple already confirms this purchase; server confirmation is pending."
    }
}
