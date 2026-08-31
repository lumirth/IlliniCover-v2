import SwiftUI

struct CoverReportSeed: Identifiable {
    let id = UUID()
    let venue: Venue
    let decision: CoverDecision?
    let interaction: CoverInteraction
}

struct CoverReportView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    let seed: CoverReportSeed
    private let priceWasPrefilled: Bool
    @State private var includeCover: Bool
    @State private var price: Int
    @State private var touched = false
    @State private var vantage: VantagePoint = .unknown
    @State private var vibes: [VibeDimension: String] = [:]
    @State private var submitting = false
    @State private var error: String?

    init(seed: CoverReportSeed) {
        self.seed = seed
        let cents = seed.decision?.price.scalarCents
        let normalized = cents.map(CoverPrice.normalizedReportCents) ?? 0
        let validPrefill = cents == normalized
        priceWasPrefilled = validPrefill
        _includeCover = State(initialValue: cents != nil)
        _price = State(initialValue: normalized)
        _touched = State(initialValue: cents != nil && !validPrefill)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Cover") {
                    Toggle("Report a cover price", isOn: $includeCover)
                    if includeCover {
                        Stepper(value: $price, in: 0...7_000, step: 500) {
                            Text(CoverPrice(amountCents: price, kind: "single").displayText).font(.title2.bold()).monospacedDigit()
                        }
                        .onChange(of: price) { touched = true }
                        HStack { ForEach([0, 500, 1_000, 2_000], id: \.self) { value in Button(CoverPrice(amountCents: value, kind: "single").displayText) { price = value; touched = true } } }
                    }
                }
                Section("Where are you?") {
                    Picker("Vantage point", selection: $vantage) {
                        ForEach(VantagePoint.allCases, id: \.self) { Text($0.rawValue.capitalized).tag($0) }
                    }
                }
                ForEach(VibeDimension.allCases, id: \.self) { vibeSection($0) }
                if environment.settings.includeLocation { Section { Label("Approximate location will accompany this report", systemImage: "location") } }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle("Report \(seed.venue.name)")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(submitting ? "Sending…" : "Send") { submit() }.disabled(submitting || (!includeCover && vibes.isEmpty)) }
            }
        }
    }

    private func vibeSection(_ dimension: VibeDimension) -> some View {
        Section(dimension.rawValue.replacingOccurrences(of: "_", with: " ").capitalized) {
            Picker("Observation", selection: Binding(get: { vibes[dimension] ?? "" }, set: { vibes[dimension] = $0.nilIfBlank })) {
                Text("Not reporting").tag("")
                ForEach(VibeInput.choices[dimension] ?? [], id: \.value) { Text($0.label).tag($0.value) }
            }
        }
    }

    private func submit() {
        submitting = true
        Task {
            let now = Date.now, id = UUID().uuidString
            let location = environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil
            let request = CoverSubmissionRequest(
                clientPlatform: "ios",
                cover: includeCover ? .init(
                    interaction: seed.interaction,
                    priceCents: CoverPrice.normalizedReportCents(price),
                    pricePrefilled: priceWasPrefilled,
                    priceTouched: touched,
                    displayedSource: seed.decision?.source,
                    displayedPriceKind: seed.decision?.price.kind,
                    displayedAmountCents: seed.decision?.price.amountCents,
                    displayedLowCents: seed.decision?.price.lowCents,
                    displayedHighCents: seed.decision?.price.highCents
                ) : nil,
                entryPoint: "cover_report",
                location: location,
                observedAt: now,
                submissionId: id,
                vantagePoint: vantage,
                venueId: seed.venue.id,
                vibes: vibes.map { .init(dimension: $0.key, value: $0.value) }
            )
            let outcome = await environment.submitCover(request)
            submitting = false
            if outcome == .failed { error = outcome.coverNotice; Haptics.warning() }
            else { environment.globalNotice = outcome.coverNotice; Haptics.success(); dismiss() }
        }
    }
}
