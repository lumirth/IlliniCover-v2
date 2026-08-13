import SwiftUI

struct AccountView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var confirmation: Confirmation?
    @State private var isWorking = false
    @State private var errorMessage: String?

    private enum Confirmation: String, Identifiable {
        case signOut, deleteAccount, rotateGuest
        var id: String { rawValue }
    }

    var body: some View {
        Form {
            if environment.hasPendingAccountDeletion {
                Section {
                    Label("Account deletion pending", systemImage: "clock.badge.exclamationmark")
                        .accessibilityIdentifier("account-deletion-pending")
                    Button(isWorking ? "Checking…" : "Check Deletion Status") {
                        retryPendingDeletion()
                    }
                    Button("Sign In to Finish Deletion") {
                        router.sheet = .signIn
                    }
                } footer: {
                    Text("Private data on this device is cleared and reporting is paused. IlliniCover will keep checking the same deletion receipt. If the old session expired, sign in to the same account to finish; IlliniCover will never delete a different account.")
                }
            } else if let account = environment.account {
                Section {
                    LabeledContent("Email", value: account.email)
                    if let firstName = account.firstName { LabeledContent("Name", value: firstName) }
                    if let graduationYear = account.graduationYear { LabeledContent("Class", value: String(graduationYear)) }
                    LabeledContent("IlliniCover Blue", value: environment.premium ? "Active" : "Not active")
                } header: {
                    Text("Profile")
                } footer: {
                    Text("Your stable account ID, not your email, owns Blue access and device links.")
                }
                Section {
                    Button("Manage IlliniCover Blue") { router.push(.premium) }
                    Button("Sign Out") { confirmation = .signOut }
                    Button("Delete Account", role: .destructive) { confirmation = .deleteAccount }
                }
            } else if environment.hasAccountLinkConflict {
                Section {
                    Label("Reporting paused", systemImage: "person.crop.circle.badge.exclamationmark")
                        .accessibilityIdentifier("account-link-conflict")
                    Button("Sign In to the Owning Account") { router.sheet = .signIn }
                } footer: {
                    Text("This installation belongs to a different account, whose report attribution may still be active. IlliniCover will not create or send reports until that account signs in or you delete and rotate this installation.")
                }
                Section("Installation privacy") {
                    Button("Delete and Rotate This Installation", role: .destructive) { confirmation = .rotateGuest }
                }
            } else if environment.installationMayRemainAccountLinked {
                Section {
                    Label("Signed out on this device", systemImage: "person.crop.circle.badge.checkmark")
                    Button("Sign In with Email") { router.sheet = .signIn }
                } footer: {
                    Text("Reports made while signed out are guest reports. This installation keeps its prior account link only for deletion and privacy ownership until you sign in again, delete the installation, or delete the account.")
                }
                Section("Installation privacy") {
                    Button("Delete or Rotate This Installation", role: .destructive) { confirmation = .rotateGuest }
                }
            } else {
                Section {
                    Label("Browsing and reporting as a guest", systemImage: "person.crop.circle.dashed")
                    Button("Sign In with Email") { router.sheet = .signIn }
                } footer: {
                    Text("Reporting does not require an account. Sign in only to use IlliniCover Blue across devices.")
                }
                Section("Guest privacy") {
                    Button("Delete or Rotate This Guest", role: .destructive) { confirmation = .rotateGuest }
                }
            }

            if let errorMessage { Section { Text(errorMessage).foregroundStyle(.red) } }
        }
        .navigationTitle("Account")
        .disabled(isWorking)
        .alert(item: $confirmation) { confirmation in
            switch confirmation {
            case .signOut:
                Alert(title: Text("Sign out?"), message: Text("Your account session and Blue access will end. New reports will be guest-attributed. The installation keeps its account link only for deletion and privacy ownership until you sign in again, delete the installation, or delete the account."), primaryButton: .destructive(Text("Sign Out")) { signOut() }, secondaryButton: .cancel())
            case .deleteAccount:
                Alert(title: Text("Delete account?"), message: Text("Credentials, sessions, account links, Blue access state, and private preferences will be deleted. This cannot be undone."), primaryButton: .destructive(Text("Delete Account")) { deleteAccount() }, secondaryButton: .cancel())
            case .rotateGuest:
                Alert(title: Text("Delete this installation identity?"), message: Text("This removes its durable account link, rotates the installation credential, and clears cached private data and queued reports on this device."), primaryButton: .destructive(Text("Delete and Rotate")) { rotateGuest() }, secondaryButton: .cancel())
            }
        }
    }

    private func signOut() {
        isWorking = true
        Task {
            do { try await environment.signOut() }
            catch { errorMessage = error.localizedDescription; isWorking = false; Haptics.warning(); return }
            isWorking = false
            dismiss()
        }
    }

    private func deleteAccount() {
        isWorking = true; errorMessage = nil
        Task {
            do { try await environment.deleteAccount(); dismiss() }
            catch { errorMessage = error.localizedDescription; Haptics.warning() }
            isWorking = false
        }
    }

    private func rotateGuest() {
        isWorking = true; errorMessage = nil
        Task {
            do { try await environment.rotateGuestActor(); Haptics.success() }
            catch { errorMessage = error.localizedDescription; Haptics.warning() }
            isWorking = false
        }
    }

    private func retryPendingDeletion() {
        isWorking = true; errorMessage = nil
        Task {
            await environment.didEnterForeground()
            if environment.hasPendingAccountDeletion {
                errorMessage = environment.globalNotice ?? APIClientError.destructiveRequestUnconfirmed.localizedDescription
                Haptics.warning()
            } else {
                Haptics.success()
            }
            isWorking = false
        }
    }
}
