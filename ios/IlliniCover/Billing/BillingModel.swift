import Foundation
import Observation
import RevenueCat

enum BluePlanKind: Int, Comparable, Sendable {
    case annual
    case monthly
    case weekly
    case sixMonth
    case lifetime

    init?(packageType: RevenueCat.PackageType) {
        switch packageType {
        case .annual: self = .annual
        case .monthly: self = .monthly
        case .weekly: self = .weekly
        case .sixMonth: self = .sixMonth
        case .lifetime: self = .lifetime
        case .unknown, .custom, .threeMonth, .twoMonth: return nil
        }
    }

    static func < (left: Self, right: Self) -> Bool {
        left.rawValue < right.rawValue
    }

    var isPrimary: Bool {
        self == .annual || self == .monthly
    }

    var isBestSubscriptionValue: Bool { self == .annual }

    var title: String {
        switch self {
        case .annual: "Annual"
        case .monthly: "Monthly"
        case .weekly: "Weekly"
        case .sixMonth: "Six months"
        case .lifetime: "Lifetime"
        }
    }

    var priceSuffix: String {
        switch self {
        case .annual: "/ year"
        case .monthly: "/ month"
        case .weekly: "/ week"
        case .sixMonth: "/ 6 months"
        case .lifetime: "once"
        }
    }

    var renewalDescription: String {
        switch self {
        case .annual: "Renews yearly until canceled."
        case .monthly: "Renews monthly until canceled."
        case .weekly: "Renews weekly until canceled."
        case .sixMonth: "Renews every six months until canceled."
        case .lifetime: "One-time purchase. No renewal."
        }
    }

    func matches(product: RevenueCat.StoreProduct) -> Bool {
        switch self {
        case .annual:
            matchesSubscription(product, value: 1, unit: .year)
        case .monthly:
            matchesSubscription(product, value: 1, unit: .month)
        case .weekly:
            matchesSubscription(product, value: 1, unit: .week)
        case .sixMonth:
            matchesSubscription(product, value: 6, unit: .month)
        case .lifetime:
            product.productType == .nonConsumable && product.subscriptionPeriod == nil
        }
    }

    private func matchesSubscription(
        _ product: RevenueCat.StoreProduct,
        value: Int,
        unit: RevenueCat.SubscriptionPeriod.Unit
    ) -> Bool {
        product.productType == .autoRenewableSubscription
            && product.subscriptionPeriod?.value == value
            && product.subscriptionPeriod?.unit == unit
    }
}

enum BlueAccessState: Equatable, Sendable {
    case inactive
    case awaitingServerConfirmation
    case active

    init(serverPremium: Bool, clientPremium: Bool) {
        if serverPremium {
            self = .active
        } else if clientPremium {
            self = .awaitingServerConfirmation
        } else {
            self = .inactive
        }
    }

    var permitsPurchase: Bool { self == .inactive }
}

enum BillingPurchaseOutcome: Equatable, Sendable {
    case completed
    case cancelled

    init(userCancelled: Bool) {
        self = userCancelled ? .cancelled : .completed
    }
}

enum BillingRestoreOutcome: Equatable, Sendable {
    case entitlementFound
    case noEntitlement

    init(clientPremium: Bool) {
        self = clientPremium ? .entitlementFound : .noEntitlement
    }
}

@MainActor
@Observable
final class BillingModel {
    private let apiKey: String?
    private var configuredAccountID: String?
    private var accountAccessEnabled = false
    private(set) var deletedIdentityWasRetired = false

    var packages: [RevenueCat.Package] = []
    var isLoading = false
    var errorMessage: String?
    private(set) var clientPremium: Bool
    private(set) var hasManageableSubscription: Bool

    init(
        apiKey: String?,
        initialPackages: [RevenueCat.Package] = [],
        initialClientPremium: Bool = false,
        initialHasActiveSubscription: Bool = false
    ) {
        self.apiKey = apiKey
        packages = initialPackages
        clientPremium = initialClientPremium
        hasManageableSubscription = initialHasActiveSubscription
    }

    /// True only while the app itself has an authenticated account. RevenueCat
    /// can stay identified between sessions so the next account switch uses
    /// `logIn`, but that retained identity must never authorize signed-out UI.
    var isConfigured: Bool { accountAccessEnabled && configuredAccountID != nil }
    var currentAccountID: String? { configuredAccountID }

    func configure(for accountID: String) async {
        guard let apiKey, !apiKey.isEmpty else {
            errorMessage = "Purchases are not configured in this build."
            return
        }

        do {
            if configuredAccountID == nil && !Purchases.isConfigured {
                Purchases.logLevel = .warn
                Purchases.configure(withAPIKey: apiKey, appUserID: accountID)
            } else if configuredAccountID != accountID {
                _ = try await Purchases.shared.logIn(accountID)
            }
            configuredAccountID = accountID
            accountAccessEnabled = true
            deletedIdentityWasRetired = false
            try await refresh()
        } catch {
            accountAccessEnabled = false
            errorMessage = error.localizedDescription
        }
    }

    func refresh() async throws {
        guard isConfigured else { return }
        isLoading = true
        defer { isLoading = false }
        let offerings = try await Purchases.shared.offerings()
        packages = offerings.current?.availablePackages ?? []
        let info = try await Purchases.shared.customerInfo()
        apply(info)
    }

    /// Refreshes only the provider-side ownership receipt. The server remains
    /// authoritative for feature access; this read lets a pending screen
    /// recover if Apple no longer reports the purchase.
    func refreshClientEntitlement() async throws {
        guard isConfigured else { throw BillingError.signInRequired }
        isLoading = true
        defer { isLoading = false }
        apply(try await Purchases.shared.customerInfo())
    }

    func purchase(_ package: RevenueCat.Package) async throws -> BillingPurchaseOutcome {
        guard !clientPremium else { throw BillingError.serverConfirmationPending }
        guard isConfigured else { throw BillingError.signInRequired }
        isLoading = true
        defer { isLoading = false }
        let result = try await Purchases.shared.purchase(package: package)
        let outcome = BillingPurchaseOutcome(userCancelled: result.userCancelled)
        if outcome == .completed {
            apply(result.customerInfo)
        }
        return outcome
    }

    func restore() async throws -> BillingRestoreOutcome {
        guard isConfigured else { throw BillingError.signInRequired }
        isLoading = true
        defer { isLoading = false }
        do {
            let info = try await Purchases.shared.restorePurchases()
            apply(info)
            return BillingRestoreOutcome(clientPremium: clientPremium)
        } catch {
            if Self.isReceiptOwnershipError(error) {
                throw BillingError.receiptOwnedByAnotherAccount
            }
            throw error
        }
    }

    func disableForSignedOutState() {
        accountAccessEnabled = false
        packages = []
        clearClientEntitlement()
        errorMessage = nil
        // RevenueCat intentionally remains identified. Product code does not
        // access it while signed out; the next account switch uses logIn(UUID).
    }

    /// Used only when the backend proves the account/session is gone (for
    /// example deletion from another linked device). Regular sign-out retains
    /// the original App User ID for safe account switching; deletion must not
    /// leave an SDK capable of recreating that provider identity.
    func retireDeletedAccountIdentity() async {
        deletedIdentityWasRetired = true
        accountAccessEnabled = false
        packages = []
        clearClientEntitlement()
        errorMessage = nil
        if configuredAccountID != nil, Purchases.isConfigured {
            _ = try? await Purchases.shared.logOut()
        }
        configuredAccountID = nil
    }

    private func apply(_ info: RevenueCat.CustomerInfo) {
        clientPremium = info.entitlements["premium"]?.isActive == true
        hasManageableSubscription = !info.activeSubscriptions.isEmpty
    }

    private func clearClientEntitlement() {
        clientPremium = false
        hasManageableSubscription = false
    }

    static func isReceiptOwnershipError(_ error: Error) -> Bool {
        let nsError = error as NSError
        let code = ErrorCode(rawValue: nsError.code)
        return code == .receiptAlreadyInUseError || code == .receiptInUseByOtherSubscriberError
    }
}

enum BillingError: LocalizedError, Equatable {
    case signInRequired
    case serverConfirmationPending
    case receiptOwnedByAnotherAccount

    var errorDescription: String? {
        switch self {
        case .signInRequired:
            "Sign in to purchase or restore IlliniCover Blue."
        case .serverConfirmationPending:
            "Apple already confirms a Blue purchase. Wait for IlliniCover to confirm access before trying again."
        case .receiptOwnedByAnotherAccount:
            "This purchase belongs to another IlliniCover account. Sign in to the original account, then restore again. Blue access cannot be silently transferred between accounts."
        }
    }
}

extension BillingModel {
    static func initialPackages(forUITesting enabled: Bool) -> [RevenueCat.Package] {
#if DEBUG
        enabled ? blueUITestPackages : []
#else
        []
#endif
    }
}

#if DEBUG
extension BillingModel {
    static var blueUITestPackages: [RevenueCat.Package] {
        [
            blueUITestPackage(
                kind: .lifetime,
                identifier: "$rc_lifetime",
                productIdentifier: "com.illinicover.app.premium.lifetime",
                localizedPrice: "$24.99",
                price: 24.99
            ),
            blueUITestPackage(
                kind: .monthly,
                identifier: "$rc_monthly",
                productIdentifier: "com.illinicover.app.premium.monthly",
                localizedPrice: "$1.99",
                price: 1.99
            ),
            blueUITestPackage(
                kind: .weekly,
                identifier: "$rc_weekly",
                productIdentifier: "com.illinicover.app.premium.weekly",
                localizedPrice: "$0.99",
                price: 0.99
            ),
            blueUITestPackage(
                kind: .annual,
                identifier: "$rc_annual",
                productIdentifier: "com.illinicover.app.premium.yearly",
                localizedPrice: "$12.99",
                price: 12.99
            ),
            blueUITestPackage(
                kind: .sixMonth,
                identifier: "$rc_six_month",
                productIdentifier: "com.illinicover.app.premium.sixmonth",
                localizedPrice: "$7.99",
                price: 7.99
            ),
        ]
    }

    private static func blueUITestPackage(
        kind: BluePlanKind,
        identifier: String,
        productIdentifier: String,
        localizedPrice: String,
        price: Decimal
    ) -> RevenueCat.Package {
        let product = RevenueCat.TestStoreProduct(
            localizedTitle: "IlliniCover Blue \(kind.title)",
            price: price,
            currencyCode: "USD",
            localizedPriceString: localizedPrice,
            productIdentifier: productIdentifier,
            productType: kind == .lifetime ? .nonConsumable : .autoRenewableSubscription,
            localizedDescription: "IlliniCover Blue",
            subscriptionGroupIdentifier: kind == .lifetime ? nil : "illinicover-blue",
            subscriptionPeriod: kind.subscriptionPeriod,
            locale: Locale(identifier: "en_US")
        )
        return RevenueCat.Package(
            identifier: identifier,
            packageType: kind.packageType,
            storeProduct: product.toStoreProduct(),
            offeringIdentifier: "default",
            webCheckoutUrl: nil
        )
    }
}

private extension BluePlanKind {
    var packageType: RevenueCat.PackageType {
        switch self {
        case .annual: .annual
        case .monthly: .monthly
        case .weekly: .weekly
        case .sixMonth: .sixMonth
        case .lifetime: .lifetime
        }
    }

    var subscriptionPeriod: RevenueCat.SubscriptionPeriod? {
        switch self {
        case .annual: .init(value: 1, unit: .year)
        case .monthly: .init(value: 1, unit: .month)
        case .weekly: .init(value: 1, unit: .week)
        case .sixMonth: .init(value: 6, unit: .month)
        case .lifetime: nil
        }
    }
}
#endif
