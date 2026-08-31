import SwiftUI

struct AccountView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var showSignIn = false
    @State private var confirmation: Action?
    @State private var working = false
    @State private var error: String?

    private enum Action: String, Identifiable { case signOut, deleteAccount, rotateGuest; var id: Self { self } }

    var body: some View {
        Form {
            if let account = environment.account {
                Section("Profile") {
                    LabeledContent("Email", value: account.email)
                    if let name = account.displayName.nilIfBlank { LabeledContent("Name", value: name) }
                    LabeledContent("IlliniCover Blue", value: environment.premium ? "Active" : "Not active")
                }
                Section {
                    NavigationLink("Manage IlliniCover Blue") { PremiumView() }
                    Button("Sign Out") { confirmation = .signOut }
                    Button("Delete Account", role: .destructive) { confirmation = .deleteAccount }
                }
            } else {
                Section {
                    Label("Browsing and reporting as a guest", systemImage: "person.crop.circle.dashed")
                    Button("Sign In with Email") { showSignIn = true }
                }
                Section("Guest privacy") { Button("Delete and Rotate This Guest", role: .destructive) { confirmation = .rotateGuest } }
            }
            if let error { Section { Text(error).foregroundStyle(.red) } }
        }
        .navigationTitle("Account")
        .disabled(working)
        .sheet(isPresented: $showSignIn) { NavigationStack { SignInFlow() } }
        .alert(item: $confirmation) { action in
            Alert(
                title: Text(action == .signOut ? "Sign out?" : (action == .deleteAccount ? "Delete account?" : "Delete guest identity?")),
                message: Text(action == .signOut ? "Blue access will end on this device." : "Private local data and queued reports will be deleted. This cannot be undone."),
                primaryButton: .destructive(Text(action == .signOut ? "Sign Out" : "Delete")) { perform(action) },
                secondaryButton: .cancel()
            )
        }
    }

    private func perform(_ action: Action) {
        working = true; error = nil
        Task {
            do {
                switch action {
                case .signOut: try await environment.signOut()
                case .deleteAccount: try await environment.deleteAccount()
                case .rotateGuest: try await environment.rotateGuestActor()
                }
                Haptics.success()
            } catch { self.error = error.localizedDescription; Haptics.warning() }
            working = false
        }
    }
}
