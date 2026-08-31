import SwiftUI

struct SupportView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var venue = ""
    @State private var issue = ""
    @State private var failed = false

    var body: some View {
        Form {
            Section("Helpful context") { TextField("Venue (optional)", text: $venue); TextEditor(text: $issue).frame(minHeight: 120) }
            Section {
                if environment.configuration.supportEmail == nil { Text("Support email is not configured in this build.").foregroundStyle(.secondary) }
                else { Button("Report a Problem", systemImage: "envelope") { openMail() }.disabled(issue.nilIfBlank == nil) }
            } footer: { Text("Your mail app opens a draft that you review before sending. Credentials, report bodies, and location are never attached.") }
        }
        .navigationTitle("Support")
        .alert("Mail could not be opened", isPresented: $failed) { Button("OK") {} }
    }

    private func openMail() {
        guard let email = environment.configuration.supportEmail else { return }
        var components = URLComponents(); components.scheme = "mailto"; components.path = email
        components.queryItems = [
            URLQueryItem(name: "subject", value: "IlliniCover problem report"),
            URLQueryItem(name: "body", value: "What happened?\n\(issue)\n\nVenue: \(venue.nilIfBlank ?? "Not supplied")\niOS: \(UIDevice.current.systemVersion)"),
        ]
        guard let url = components.url else { failed = true; return }
        Task { if !(await UIApplication.shared.open(url)) { failed = true } }
    }
}
