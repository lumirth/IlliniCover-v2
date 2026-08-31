import SwiftUI

private enum OnboardingStep {
    case welcome
    case signIn
    case location
}

struct OnboardingFlow: View {
    @State private var step: OnboardingStep = .welcome

    var body: some View {
        NavigationStack {
            switch step {
            case .welcome:
                WelcomeView(
                    continueWithEmail: { step = .signIn },
                    continueAsGuest: { step = .location }
                )
            case .signIn:
                SignInFlow(
                    onComplete: { step = .location },
                    onCancel: { step = .welcome }
                )
            case .location:
                LocationOnboardingView(isPresentedModally: false)
            }
        }
    }
}

private struct WelcomeView: View {
    let continueWithEmail: () -> Void
    let continueAsGuest: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Welcome to")
                    Text("IlliniCover")
                        .foregroundStyle(ICTheme.accent)
                }
                .font(.largeTitle.bold())
                .accessibilityElement(children: .combine)

                VStack(spacing: 24) {
                    FeatureRow(icon: "dollarsign.circle.fill", color: ICTheme.accent, title: "Live Cover Prices", detail: "See what the cover is before you walk all the way down Green Street.")
                    FeatureRow(icon: "sparkles", color: ICTheme.estimate, title: "Cover Estimates", detail: "No recent reports? See an estimate based on past reports in similar conditions.")
                    FeatureRow(icon: "checkmark.shield.fill", color: ICTheme.right, title: "Community Reports", detail: "Confirm or correct a price in a few taps. Recent reports keep everyone up to date.")
                }

                VStack(spacing: 10) {
                    Button("Continue with Email", action: continueWithEmail)
                        .buttonStyle(PrimaryActionStyle())
                        .accessibilityIdentifier("onboarding-email")
                    Button("Continue as Guest", action: continueAsGuest)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .accessibilityIdentifier("onboarding-guest")
                }
            }
            .padding(24)
        }
        .background(ICTheme.background)
        .navigationBarBackButtonHidden()
    }
}

private struct FeatureRow: View {
    let icon: String
    let color: Color
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(color)
                .frame(width: 34)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }
}

struct LocationOnboardingView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    let isPresentedModally: Bool

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            Image(systemName: "location.circle.fill")
                .font(.system(size: 72))
                .foregroundStyle(ICTheme.accent)
            Text("Location adds context")
                .font(.largeTitle.bold())
                .multilineTextAlignment(.center)
            Text("When you send a report with location enabled, IlliniCover will ask then and check once. The app never tracks you continuously.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Spacer()
            Button("Include Location with Reports") { environment.settings.includeLocation = true; finish() }
            .buttonStyle(PrimaryActionStyle())
            Button("Not Now") { finish() }
                .frame(minHeight: 44)
        }
        .padding(24)
        .background(ICTheme.background)
        .navigationBarBackButtonHidden()
    }

    private func finish() {
        environment.settings.onboardingComplete = true
        if isPresentedModally { dismiss() }
    }
}
