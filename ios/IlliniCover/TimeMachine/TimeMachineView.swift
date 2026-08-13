import Observation
import SwiftUI

@MainActor
@Observable
private final class TimeMachineModel {
    var venue: Venue?
    var target = Date.now
    var result: TimeMachineResponse?
    var isLoading = false
    var errorMessage: String?

    func loadVenue(id: String, api: any AppAPI) async {
        if let detail = try? await api.venueCover(id: id) { venue = detail.venue }
    }

    func query(venueID: String, api: any AppAPI) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await Task.sleep(for: .milliseconds(300))
            try Task.checkCancellation()
            result = try await api.timeMachine(venueID: venueID, target: target)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct TimeMachineView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    let venueID: String
    @State private var model = TimeMachineModel()

    var body: some View {
        Group {
            if environment.account == nil {
                ContentUnavailableView {
                    Label("Sign in for Time Machine", systemImage: "person.crop.circle.badge.clock")
                } description: {
                    Text("IlliniCover Blue belongs to an IlliniCover account so it works across devices.")
                } actions: {
                    Button("Sign In") { router.sheet = .signIn }.buttonStyle(.borderedProminent)
                }
            } else if !environment.premium {
                ContentUnavailableView {
                    Label("IlliniCover Blue feature", systemImage: "clock.arrow.circlepath")
                } description: {
                    Text("Explore supported past times and future cover predictions.")
                } actions: {
                    Button("View IlliniCover Blue") { router.push(.premium) }.buttonStyle(.borderedProminent)
                }
            } else {
                machine
            }
        }
        .navigationTitle("Time Machine")
        .task { await model.loadVenue(id: venueID, api: environment.api) }
    }

    private var machine: some View {
        Form {
            Section {
                DatePicker("Date and time", selection: $model.target, displayedComponents: [.date, .hourAndMinute])
            } header: {
                Text(model.venue?.name ?? "Cover at")
            }

            Section {
                if model.isLoading {
                    HStack { Spacer(); ProgressView(); Spacer() }
                } else if let result = model.result {
                    VStack(spacing: 10) {
                        Text(result.cover.price.displayText)
                            .font(.system(size: 58, weight: .bold, design: .rounded))
                            .foregroundStyle(ICTheme.estimate)
                        Text(result.mode.title)
                            .font(.headline)
                        Text(result.cover.evidenceText)
                            .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
                } else if let error = model.errorMessage {
                    Text(error).foregroundStyle(.red)
                } else {
                    Text("Choose a time to see IlliniCover’s best answer.").foregroundStyle(.secondary)
                }
            }

            Section {
                Text("Past results are reconstructions, current results are assessments, and future results are predictions using evidence available at the server cutoff. They are not official archived venue prices.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .task(id: model.target) { await model.query(venueID: venueID, api: environment.api) }
    }
}
