import RevenueCat
import SwiftUI

struct PremiumView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var notice: String?
    @State private var signIn = false
    private let terms = URL(string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")!
    private let subscriptions = URL(string: "https://apps.apple.com/account/subscriptions")!

    var body: some View {
        List {
            Section {
                Image(systemName: "sparkles").font(.system(size: 40)).foregroundStyle(ICTheme.accent)
                Text("Know before you go.").font(.title2.bold())
                Label("Past and future Time Machine views", systemImage: "clock.arrow.circlepath")
                Label("Extended venue report history", systemImage: "list.bullet.rectangle")
            }
            if environment.premium {
                Section { Label("IlliniCover Blue is active", systemImage: "checkmark.seal.fill").foregroundStyle(ICTheme.right); Link("Manage Apple Subscriptions", destination: subscriptions) }
            } else if environment.account == nil {
                Section { Button("Sign In to Continue") { signIn = true } } footer: { Text("An account is required so purchases work across devices.") }
            } else if environment.billing.clientPremium {
                Section("Confirmation pending") {
                    Text("Apple confirms the purchase. Server-protected tools remain locked until IlliniCover confirms access.")
                    Button("Check Again") { refresh() }
                    Link("Manage Apple Subscriptions", destination: subscriptions)
                }
            } else {
                Section("Choose a plan") {
                    if environment.billing.isLoading { ProgressView("Loading plans…") }
                    ForEach(environment.billing.packages, id: \.identifier) { package in
                        Button { purchase(package) } label: {
                            HStack { VStack(alignment: .leading) { Text(package.storeProduct.localizedTitle).font(.headline); Text(package.storeProduct.localizedDescription).font(.caption).foregroundStyle(.secondary) }; Spacer(); Text(priceTerms(package)).bold() }
                        }
                    }
                    if environment.billing.packages.isEmpty && !environment.billing.isLoading { Text(environment.billing.errorMessage ?? "Purchase options are unavailable.").foregroundStyle(.secondary) }
                    Button("Restore Purchases") { restore() }
                }
            }
            Section { if let url = environment.configuration.privacyPolicyURL { Link("Privacy Policy", destination: url) }; Link("Terms of Use", destination: terms) }
            if let notice { Section { Text(notice) } }
        }
        .navigationTitle("IlliniCover Blue")
        .sheet(isPresented: $signIn) { NavigationStack { SignInFlow() } }
        .task { if let account = environment.account { await environment.billing.configure(for: account.id); _ = await environment.refreshEntitlement() } }
    }

    private func purchase(_ package: RevenueCat.Package) {
        Task {
            do {
                guard try await environment.billing.purchase(package) else { return }
                _ = await environment.refreshEntitlement()
                notice = environment.premium ? "IlliniCover Blue is active." : "Apple confirmed your purchase; server confirmation is pending."
            } catch { notice = error.localizedDescription }
        }
    }

    private func restore() {
        Task {
            do {
                let found = try await environment.billing.restore(); _ = await environment.refreshEntitlement()
                notice = environment.premium ? "IlliniCover Blue restored." : (found ? "Purchase found; server confirmation is pending." : "No active purchase was found.")
            } catch { notice = error.localizedDescription }
        }
    }

    private func refresh() { Task { _ = try? await environment.billing.refresh(); _ = await environment.refreshEntitlement() } }

    private func priceTerms(_ package: RevenueCat.Package) -> String {
        let product = package.storeProduct
        guard let period = product.subscriptionPeriod else { return "\(product.localizedPriceString) one-time" }
        let unit: String
        switch period.unit {
        case .day: unit = "day"
        case .week: unit = "week"
        case .month: unit = "month"
        case .year: unit = "year"
        @unknown default: unit = "period"
        }
        return period.value == 1 ? "\(product.localizedPriceString) / \(unit)" : "\(product.localizedPriceString) / \(period.value) \(unit)s"
    }
}
