import SwiftUI

struct TimeMachineView: View {
    @Environment(AppEnvironment.self) private var environment
    let venue: Venue
    @State private var target = Date.now
    @State private var result: TimeMachineResponse?
    @State private var loading = false
    @State private var error: String?

    var body: some View {
        Form {
            Section("When") {
                DatePicker("Target time", selection: $target)
                Button(loading ? "Checking…" : "Check cover") { query() }.disabled(loading)
            }
            if let result {
                Section(result.mode.title) {
                    LabeledContent("Cover", value: result.cover?.price.displayText ?? "Unavailable")
                    LabeledContent("Source", value: result.cover?.presentationSourceLabel ?? "No evidence")
                    Text("Knowledge cutoff: \(result.knowledgeCutoff.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let error { Section { Text(error).foregroundStyle(.red) } }
            if !environment.premium { Section { NavigationLink("Unlock IlliniCover Blue") { PremiumView() } } }
        }
        .navigationTitle("Time Machine")
    }

    private func query() {
        loading = true; error = nil
        Task {
            do { result = try await environment.api.timeMachine(venue.id, target: target) }
            catch { self.error = error.localizedDescription }
            loading = false
        }
    }
}
