import SwiftUI

struct SignInFlow: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    var onComplete: (() -> Void)?
    var onCancel: (() -> Void)?
    @State private var email = ""
    @State private var code = ""
    @State private var sent = false
    @State private var intent: EmailCodeIntent = .signIn
    @State private var working = false
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                if sent {
                    TextField("XXXX-XXXX code", text: $code)
                        .textContentType(.oneTimeCode).textInputAutocapitalization(.characters).autocorrectionDisabled()
                        .onChange(of: code) { _, value in
                            let letters = value.uppercased().filter(\.isLetter).prefix(8)
                            code = letters.count > 4 ? "\(letters.prefix(4))-\(letters.dropFirst(4))" : String(letters)
                        }
                        .accessibilityIdentifier("email-code")
                } else {
                    Picker("Action", selection: $intent) { Text("Sign In").tag(EmailCodeIntent.signIn); Text("Create Account").tag(EmailCodeIntent.signUp) }.pickerStyle(.segmented)
                    TextField("Email", text: $email).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("email-address")
                }
                if let error { Text(error).foregroundStyle(.red).accessibilityIdentifier("sign-in-error") }
            } footer: { Text(sent ? "Enter the code sent to \(email)." : "Use any email you can verify. No password is required.") }
            Section {
                Button(sent ? "Verify Code" : "Email Me a Code") { submit() }
                    .disabled(working || (sent ? code.filter(\.isLetter).count != 8 : !email.contains("@")))
                if sent {
                    Button("Resend Code") { Task { do { try await environment.api.resendEmailCode(intent) } catch { self.error = error.localizedDescription } } }
                    Button("Use a Different Email") { Task { try? await environment.credentials.delete(.emailChallengeToken) }; sent = false; code = "" }
                }
            }
        }
        .navigationTitle(sent ? "Check Your Email" : "Sign In")
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { cancel() }.disabled(working) } }
        .onDisappear { Task { try? await environment.credentials.delete(.emailChallengeToken) } }
    }

    private func cancel() { if let onCancel { onCancel() } else { dismiss() } }

    private func submit() {
        working = true; error = nil
        Task {
            defer { working = false }
            do {
                if sent {
                    try await environment.authenticate(code, intent: intent)
                    Haptics.success(); if let onComplete { onComplete() } else { dismiss() }
                } else {
                    _ = try await environment.api.requestEmailCode(email.trimmingCharacters(in: .whitespacesAndNewlines), intent: intent)
                    sent = true
                }
            } catch { self.error = error.localizedDescription; Haptics.warning() }
        }
    }
}
