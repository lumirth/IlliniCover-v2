import Observation
import SwiftUI

@MainActor
@Observable
private final class EstimateDetailModel {
    var detail: VenueCoverResponse?
    var errorMessage: String?
    var isLoading = true

    func load(venueID: String, api: any AppAPI) async {
        isLoading = detail == nil
        defer { isLoading = false }
        do {
            detail = try await api.venueCover(id: venueID)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct EstimateDetailView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    let venueID: String
    @State private var model = EstimateDetailModel()

    var body: some View {
        Group {
            if let detail = model.detail {
                ScrollView {
                    VStack(spacing: 18) {
                        Text(detail.cover.price.displayText)
                            .font(.system(size: 64, weight: .bold, design: .rounded))
                            .foregroundStyle(ICTheme.estimate)
                        Text("Historical estimate")
                            .font(.title2.bold())
                        Text("This is IlliniCover’s best current estimate from past reports around this time, adjusted by useful same-night context. It is not an advertised price or a fresh community report.")
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Label(detail.cover.evidenceText, systemImage: "sparkles")
                            .font(.subheadline)
                            .foregroundStyle(ICTheme.estimate)
                        Button {
                            router.push(.timeMachine(detail.venue.id))
                        } label: {
                            Label("Explore another time", systemImage: "clock.arrow.circlepath")
                                .frame(maxWidth: .infinity, minHeight: 48)
                        }
                        .buttonStyle(.bordered)
                        if let decisionID = detail.cover.decisionId {
                            Text("Decision \(decisionID)")
                                .font(.caption2.monospaced())
                                .foregroundStyle(.tertiary)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(20)
                }
            } else if model.isLoading {
                ProgressView("Loading estimate…")
            } else {
                ContentUnavailableView {
                    Label("Estimate unavailable", systemImage: "sparkles")
                } description: {
                    Text(model.errorMessage ?? "Try again.")
                } actions: {
                    Button("Retry") { Task { await model.load(venueID: venueID, api: environment.api) } }
                }
            }
        }
        .background(ICTheme.background)
        .navigationTitle("Cover Estimate")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load(venueID: venueID, api: environment.api) }
    }
}
