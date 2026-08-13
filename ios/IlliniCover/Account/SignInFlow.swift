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
    @State private var isWorking = false
    @State private var isResending = false
    @State private var resendNotice: String?
    @State private var errorMessage: String?
    @FocusState private var focusedField: Field?

    private enum Field { case email, code }

    var body: some View {
        Form {
            Section {
                if sent {
                    TextField("XXXX-XXXX code", text: $code)
                        .keyboardType(.asciiCapable)
                        .textContentType(.oneTimeCode)
                        .focused($focusedField, equals: .code)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .onChange(of: code) { _, value in
                            let characters = value.uppercased().filter(\.isLetter).prefix(8)
                            code = characters.count > 4 ? "\(characters.prefix(4))-\(characters.dropFirst(4))" : String(characters)
                        }
                        .accessibilityIdentifier("email-code")
                } else {
                    if !environment.hasPendingAccountDeletion {
                        Picker("Account action", selection: $intent) {
                            Text("Sign In").tag(EmailCodeIntent.signIn)
                            Text("Create Account").tag(EmailCodeIntent.signUp)
                        }
                        .pickerStyle(.segmented)
                    }
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textContentType(.emailAddress)
                        .focused($focusedField, equals: .email)
                        .accessibilityIdentifier("email-address")
                }
                if let errorMessage {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(errorMessage)
                        .accessibilityIdentifier("sign-in-error")
                }
            } footer: {
                Text(footerText)
            }
            if let resendNotice {
                Section { Text(resendNotice).foregroundStyle(.secondary) }
            }

            Section {
                Button(sent ? "Verify Code" : "Email Me a Code") { submit() }
                    .disabled(isWorking || (sent ? code.filter(\.isLetter).count != 8 : !email.contains("@")))
                    .accessibilityIdentifier("sign-in-submit")
                if sent {
                    Button(isResending ? "Sending Again…" : "Resend Code") { resend() }
                        .disabled(isWorking || isResending)
                        .accessibilityIdentifier("resend-code")
                    Button("Use a Different Email") {
                        Task { await environment.credentials.delete(.emailChallengeToken) }
                        sent = false
                        code = ""
                        errorMessage = nil
                        resendNotice = nil
                        focusedField = .email
                    }
                }
            }
        }
        .navigationTitle(environment.hasPendingAccountDeletion ? "Finish Deletion" : (sent ? "Check Your Email" : "Sign In"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { cancel() }
                    .disabled(isWorking)
                    .accessibilityIdentifier("sign-in-cancel")
            }
        }
        .interactiveDismissDisabled(isWorking)
        .onAppear { focusedField = sent ? .code : .email }
        // A sheet may leave through a drag rather than the toolbar button.
        // Clearing here makes every exit abandon the pending allauth flow;
        // successful verification has already rotated and removed this token.
        .onDisappear {
            Task { await SignInFlowLifecycle.abandonChallenge(in: environment.credentials) }
        }
    }

    private var footerText: String {
        if sent { return "Enter the code sent to \(email)." }
        if environment.hasPendingAccountDeletion {
            return "Sign in to the same account that requested deletion. A different account will never be deleted."
        }
        return "Use any email you can verify. No password is required."
    }


    private func resend() {
        guard sent, !isWorking, !isResending else { return }
        isResending = true
        errorMessage = nil
        resendNotice = nil
        Task {
            defer { isResending = false }
            do {
                try await environment.api.resendEmailCode(intent: intent)
                resendNotice = "A new code was sent."
                Haptics.success()
            } catch {
                errorMessage = error.localizedDescription
                Haptics.warning()
            }
        }
    }

    private func cancel() {
        guard !isWorking else { return }
        isWorking = true
        Task {
            await SignInFlowLifecycle.abandonChallenge(in: environment.credentials)
            isWorking = false
            if let onCancel { onCancel() } else { dismiss() }
        }
    }

    private func submit() {
        guard !isWorking else { return }
        isWorking = true
        errorMessage = nil
        Task {
            defer { isWorking = false }
            do {
                if sent {
                    let response = try await environment.api.verifyEmailCode(code: code, intent: intent)
                    try await environment.didAuthenticate(response.account)
                    Haptics.success()
                    if let onComplete { onComplete() } else { dismiss() }
                } else {
                    _ = try await environment.api.requestEmailCode(email: email.trimmingCharacters(in: .whitespacesAndNewlines), intent: intent)
                    sent = true
                    focusedField = .code
                }
            } catch {
                errorMessage = error.localizedDescription
                Haptics.warning()
            }
        }
    }
}

enum SignInFlowLifecycle {
    static func abandonChallenge(in credentials: CredentialStore) async {
        await credentials.delete(.emailChallengeToken)
    }
}
