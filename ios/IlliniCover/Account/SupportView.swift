import SwiftUI

struct SupportView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var venue = ""
    @State private var approximateTime = Date.now.formatted(date: .abbreviated, time: .shortened)
    @State private var decisionID = ""
    @State private var requestID = ""
    @State private var issue = ""
    @State private var cannotOpenMail = false

    var body: some View {
        Form {
            Section {
                LabeledContent("App", value: appVersion)
                LabeledContent("iOS", value: UIDevice.current.systemVersion)
            } header: {
                Text("Included automatically")
            } footer: {
                Text("IlliniCover never includes report payloads, location, email, or credentials in this diagnostic handoff.")
            }

            Section("Helpful context") {
                TextField("Venue (optional)", text: $venue)
                TextField("Approximate time", text: $approximateTime)
                TextField("Decision ID (optional)", text: $decisionID)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Request ID (optional)", text: $requestID)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            Section("What happened?") {
                TextEditor(text: $issue)
                    .frame(minHeight: 120)
                    .accessibilityLabel("Problem description")
            }

            Section {
                if environment.configuration.supportEmail == nil {
                    Label("Support email is not configured in this build.", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.secondary)
                } else {
                    Button {
                        openMail()
                    } label: {
                        Label("Report a Problem", systemImage: "envelope")
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .disabled(issue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            } footer: {
                if environment.configuration.supportEmail == nil {
                    Text("A public support address is an external-beta release gate. This surface is ready and will enable automatically when ICSupportEmail is configured.")
                } else {
                    Text("Your Mail app opens with this diagnostic summary. You review it before sending. The support mailbox retains correspondence only as long as needed to resolve and document the request, subject to legal or security preservation requirements.")
                }
            }
        }
        .navigationTitle("Support")
        .navigationBarTitleDisplayMode(.large)
        .alert("Mail could not be opened", isPresented: $cannotOpenMail) {
            Button("OK") {}
        } message: {
            Text("Check that a mail app is installed, then try again.")
        }
    }

    private var appVersion: String {
        let info = Bundle.main.infoDictionary ?? [:]
        let version = info["CFBundleShortVersionString"] as? String ?? "unknown"
        let build = info["CFBundleVersion"] as? String ?? "unknown"
        return "\(version) (\(build))"
    }

    private var messageBody: String {
        """
        What happened?
        \(issue.trimmingCharacters(in: .whitespacesAndNewlines))

        App: \(appVersion)
        OS: iOS \(UIDevice.current.systemVersion)
        Venue: \(venue.nilIfBlank ?? "Not supplied")
        Approximate time: \(approximateTime.nilIfBlank ?? "Not supplied")
        Decision ID: \(decisionID.nilIfBlank ?? "Not supplied")
        Request ID: \(requestID.nilIfBlank ?? "Not supplied")
        """
    }

    private func openMail() {
        guard let email = environment.configuration.supportEmail else { return }
        var components = URLComponents()
        components.scheme = "mailto"
        components.path = email
        components.queryItems = [
            URLQueryItem(name: "subject", value: "IlliniCover problem report"),
            URLQueryItem(name: "body", value: messageBody),
        ]
        guard let url = components.url else { cannotOpenMail = true; return }
        Task {
            if !(await UIApplication.shared.open(url)) { cannotOpenMail = true }
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
