import RevenueCat
import SwiftUI

struct PremiumView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @State private var notice: String?
    @State private var showsMoreOptions = false
    @State private var isCheckingConfirmation = false

    private static let termsOfUseURL = URL(
        string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"
    )!
    private static let manageSubscriptionsURL = URL(
        string: "https://apps.apple.com/account/subscriptions"
    )!

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 12) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundStyle(ICTheme.accent)
                    Text("Know before you go.")
                        .font(.title2.bold())
                    Text("IlliniCover Blue unlocks the planning tools that use IlliniCover’s evidence beyond tonight’s current cover.")
                        .foregroundStyle(.secondary)
                    Label("Past and future Time Machine views", systemImage: "clock.arrow.circlepath")
                    Label("Up to 90 service nights and 250 reports per venue", systemImage: "list.bullet.rectangle")
                }
                .padding(.vertical, 12)
            }

            if environment.premium {
                Section {
                    Label("IlliniCover Blue is active", systemImage: "checkmark.seal.fill")
                        .foregroundStyle(ICTheme.right)
                    if environment.billing.hasManageableSubscription {
                        Link("Manage Apple Subscriptions", destination: Self.manageSubscriptionsURL)
                    }
                } footer: {
                    Text("Protected Time Machine responses are authorized by the IlliniCover server.")
                }
            } else if environment.account == nil {
                Section {
                    Button("Sign In to Continue") { router.sheet = .signIn }
                } footer: {
                    Text("An IlliniCover account is required before purchase so Blue access works across devices.")
                }
            } else if accessState == .awaitingServerConfirmation {
                Section {
                    Label("Purchase confirmed by Apple", systemImage: "clock.arrow.circlepath")
                        .font(.headline)
                        .foregroundStyle(ICTheme.accent)
                        .accessibilityIdentifier("blue-confirmation-pending")
                    Text("IlliniCover is waiting for its server to confirm Blue access. Blue tools stay locked, and another purchase cannot be started, until that check finishes.")
                        .foregroundStyle(.secondary)
                    Button(isCheckingConfirmation ? "Checking…" : "Check Blue Access Again") {
                        checkConfirmation()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isCheckingConfirmation || environment.billing.isLoading)
                    .accessibilityIdentifier("blue-confirmation-refresh")
                    if environment.billing.hasManageableSubscription {
                        Link("Manage Apple Subscriptions", destination: Self.manageSubscriptionsURL)
                    }
                } header: {
                    Text("Confirmation pending")
                } footer: {
                    Text("Apple purchase status is not used by itself to unlock server-protected features.")
                }
            } else {
                Section {
                    if environment.billing.isLoading {
                        ProgressView("Loading plans…")
                    }
                    ForEach(primaryPlans) { plan in
                        BluePlanRow(plan: plan) { purchase(plan.package) }
                            .disabled(environment.billing.isLoading)
                    }
                    if !additionalPlans.isEmpty {
                        DisclosureGroup("Show more options", isExpanded: $showsMoreOptions) {
                            ForEach(additionalPlans) { plan in
                                BluePlanRow(plan: plan) { purchase(plan.package) }
                                    .disabled(environment.billing.isLoading)
                            }
                        }
                    }
                    if bluePlans.isEmpty && !environment.billing.isLoading {
                        Text(environment.billing.errorMessage ?? "Purchase options are unavailable in this build.")
                            .foregroundStyle(.secondary)
                    }
                    Button("Restore Purchases") { restore() }
                        .disabled(environment.billing.isLoading)
                    if environment.billing.hasManageableSubscription {
                        Link("Manage Apple Subscriptions", destination: Self.manageSubscriptionsURL)
                    }
                } header: {
                    Text("Choose a plan")
                } footer: {
                    Text("Weekly, monthly, six-month, and annual plans renew automatically through Apple until canceled. Lifetime is a one-time purchase.")
                }
            }

            Section {
                if let privacyPolicyURL = environment.configuration.privacyPolicyURL {
                    Link("Privacy Policy", destination: privacyPolicyURL)
                        .accessibilityIdentifier("blue-privacy-policy")
                }
                Link("Terms of Use", destination: Self.termsOfUseURL)
                    .accessibilityIdentifier("blue-terms-of-use")
            } header: {
                Text("Legal")
            }

            Section {
                Text("Time Machine results are reconstructions or predictions—not official archived prices. Purchases use your non-guessable account UUID, never your email, as the RevenueCat identity.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            if let notice { Section { Text(notice) } }
        }
        .navigationTitle("IlliniCover Blue")
        .task {
            if let account = environment.account {
                await environment.billing.configure(for: account.id)
                await environment.refreshEntitlement()
            }
        }
    }

    private func purchase(_ package: RevenueCat.Package) {
        Task {
            do {
                let outcome = try await environment.billing.purchase(package)
                guard outcome == .completed else { return }
                let reachedServer = await environment.refreshEntitlement()
                if environment.premium {
                    notice = "IlliniCover Blue is active."
                    Haptics.success()
                } else if environment.billing.clientPremium {
                    notice = reachedServer
                        ? "Apple confirmed your purchase. IlliniCover is still confirming Blue access."
                        : "Apple confirmed your purchase, but IlliniCover could not check Blue access. Try again shortly."
                } else {
                    notice = "The purchase completed, but Apple did not return active Blue access. Try Restore Purchases or contact support before purchasing again."
                    Haptics.warning()
                }
            } catch { notice = error.localizedDescription; Haptics.warning() }
        }
    }

    private func restore() {
        Task {
            do {
                let outcome = try await environment.billing.restore()
                let reachedServer = await environment.refreshEntitlement()
                if outcome == .noEntitlement {
                    notice = environment.premium
                        ? "IlliniCover Blue is already active on this account; Apple found no purchase to restore."
                        : "No active IlliniCover Blue purchase was found to restore."
                } else if environment.premium {
                    notice = "IlliniCover Blue restored."
                    Haptics.success()
                } else {
                    notice = reachedServer
                        ? "Apple found your Blue purchase. IlliniCover is still confirming access."
                        : "Apple found your Blue purchase, but IlliniCover could not check access. Try again shortly."
                }
            } catch { notice = error.localizedDescription; Haptics.warning() }
        }
    }

    private func checkConfirmation() {
        Task {
            isCheckingConfirmation = true
            defer { isCheckingConfirmation = false }

            var providerError: Error?
            do {
                try await environment.billing.refreshClientEntitlement()
            } catch {
                providerError = error
            }
            let reachedServer = await environment.refreshEntitlement()

            if environment.premium {
                notice = "IlliniCover Blue is active."
                Haptics.success()
            } else if environment.billing.clientPremium {
                notice = reachedServer
                    ? "Apple still confirms your purchase. IlliniCover is still confirming Blue access."
                    : "Apple confirms your purchase, but IlliniCover could not check Blue access. Try again shortly."
            } else if let providerError {
                notice = "IlliniCover could not refresh Apple purchase status: \(providerError.localizedDescription)"
                Haptics.warning()
            } else {
                notice = "Apple no longer reports an active Blue purchase. You can choose a plan or restore purchases."
            }
        }
    }

    private var accessState: BlueAccessState {
        BlueAccessState(
            serverPremium: environment.premium,
            clientPremium: environment.billing.clientPremium
        )
    }

    private var bluePlans: [BluePackage] {
        environment.billing.packages
            .compactMap { package in
                guard let kind = BluePlanKind(packageType: package.packageType),
                      kind.matches(product: package.storeProduct) else { return nil }
                return BluePackage(kind: kind, package: package)
            }
            .sorted { $0.kind < $1.kind }
    }

    private var primaryPlans: [BluePackage] {
        bluePlans.filter(\.kind.isPrimary)
    }

    private var additionalPlans: [BluePackage] {
        bluePlans.filter { !$0.kind.isPrimary }
    }
}

private struct BluePackage: Identifiable {
    let kind: BluePlanKind
    let package: RevenueCat.Package

    var id: String { package.identifier }
}

private struct BluePlanRow: View {
    let plan: BluePackage
    let purchase: () -> Void

    var body: some View {
        Button(action: purchase) {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(plan.kind.title)
                        .font(.headline)
                        .foregroundStyle(.primary)
                    if plan.kind.isBestSubscriptionValue {
                        Text("Best subscription value")
                            .font(.caption2.bold())
                            .foregroundStyle(ICTheme.accent)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(ICTheme.accent.opacity(0.12), in: .capsule)
                    }
                    Spacer(minLength: 12)
                    Text(priceLine)
                        .font(.headline)
                        .foregroundStyle(.primary)
                }
                Text(plan.kind.renewalDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
    }

    private var priceLine: String {
        "\(plan.package.storeProduct.localizedPriceString) \(plan.kind.priceSuffix)"
    }

    private var accessibilityLabel: String {
        [
            plan.kind.title,
            plan.kind.isBestSubscriptionValue ? "Best subscription value" : nil,
            priceLine,
            plan.kind.renewalDescription,
        ]
        .compactMap { $0 }
        .joined(separator: ", ")
    }
}
