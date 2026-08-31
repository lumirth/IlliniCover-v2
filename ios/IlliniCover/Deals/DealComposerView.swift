import SwiftUI

struct DealComposerSeed: Identifiable {
    let id = UUID()
    let venue: Venue
    let action: DealEvidenceAction
    var deal: Deal?
}

private enum PriceMode: String, CaseIterable, Identifiable { case single, range, percent; var id: Self { self } }
private enum TimingMode: String, CaseIterable, Identifiable { case unknown, allNight = "all night", specific; var id: Self { self } }

struct DealComposerView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    let seed: DealComposerSeed
    @State private var category: DealCategory = .drink
    @State private var name = ""
    @State private var familyID: String?
    @State private var priceMode: PriceMode = .single
    @State private var low = 500
    @State private var high = 1_000
    @State private var percent = 50
    @State private var serving = ""
    @State private var unit = ""
    @State private var timingMode: TimingMode = .unknown
    @State private var timing = ""
    @State private var whileSuppliesLast = false
    @State private var query = ""
    @State private var suggestions: [DealSuggestion] = []
    @State private var submitting = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Deal") {
                    Picker("Category", selection: $category) { ForEach(DealCategory.allCases, id: \.self) { Text($0.rawValue.capitalized).tag($0) } }
                    TextField("Name", text: $name)
                    TextField("Search prior deals", text: $query).textInputAutocapitalization(.never)
                    ForEach(suggestions.prefix(5)) { suggestion in
                        Button { apply(suggestion) } label: {
                            VStack(alignment: .leading) { Text(suggestion.displayName); Text("\(suggestion.priceText) · \(suggestion.provenanceText)").font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
                Section("Price") {
                    Picker("Price type", selection: $priceMode) { ForEach(PriceMode.allCases) { Text($0.rawValue.capitalized).tag($0) } }.pickerStyle(.segmented)
                    Stepper("\(priceMode == .range ? "Low" : "Price"): \(CoverPrice(amountCents: low, kind: "single").displayText)", value: $low, in: 0...25_000, step: 100)
                    if priceMode == .range { Stepper("High: \(CoverPrice(amountCents: high, kind: "single").displayText)", value: $high, in: low...25_000, step: 100) }
                    if priceMode == .percent { Stepper("\(percent)% off", value: $percent, in: 1...100, step: 5) }
                }
                Section("Serving") { TextField("Format, e.g. pitcher", text: $serving); TextField("Unit, e.g. 16 oz", text: $unit) }
                Section("Timing") {
                    Picker("Availability", selection: $timingMode) { ForEach(TimingMode.allCases) { Text($0.rawValue.capitalized).tag($0) } }
                    if timingMode == .specific { TextField("Example: before 10 PM", text: $timing) }
                    Toggle("While supplies last", isOn: $whileSuppliesLast)
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle(seed.action == .addMissing ? "Add Deal" : "Correct Deal")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(submitting ? "Sending…" : "Send") { submit() }.disabled(submitting || name.nilIfBlank == nil || (timingMode == .specific && timing.nilIfBlank == nil)) }
            }
            .task { apply(seed.deal) }
            .task(id: query) {
                guard query.count >= 2 else { suggestions = []; return }
                try? await Task.sleep(for: .milliseconds(250))
                if !Task.isCancelled { suggestions = (try? await environment.api.dealSuggestions(query, venueID: seed.venue.id)) ?? [] }
            }
        }
    }

    private func apply(_ deal: Deal?) {
        guard let deal else { return }
        category = DealCategory(rawValue: deal.category) ?? .drink
        name = deal.displayName; familyID = deal.canonicalFamilyId
        serving = deal.servingFormat; unit = deal.unit
        switch deal.priceKind {
        case "range": priceMode = .range; low = deal.priceLowCents ?? 0; high = deal.priceHighCents ?? low
        case "relative", "percent_off": priceMode = .percent; percent = Int(deal.discountPercent ?? 50)
        default: priceMode = .single; low = deal.priceCents ?? 0
        }
        applyTiming(known: deal.timingKnown, description: deal.timingDescription, whileSuppliesLast: deal.whileSuppliesLast)
    }

    private func apply(_ suggestion: DealSuggestion) {
        category = DealCategory(rawValue: suggestion.category) ?? .drink
        name = suggestion.displayName; familyID = suggestion.canonicalFamilyId
        serving = suggestion.servingFormat; unit = suggestion.unit
        switch suggestion.priceKind {
        case "range": priceMode = .range; low = suggestion.priceLowCents ?? 0; high = suggestion.priceHighCents ?? low
        case "relative", "percent_off": priceMode = .percent; percent = Int(suggestion.discountPercent ?? 50)
        default: priceMode = .single; low = suggestion.priceCents ?? 0
        }
        applyTiming(known: suggestion.timingKnown, description: suggestion.timingDescription, whileSuppliesLast: suggestion.whileSuppliesLast)
        query = ""; suggestions = []
    }

    private func applyTiming(known: Bool, description: String?, whileSuppliesLast: Bool) {
        timing = description ?? ""
        self.whileSuppliesLast = whileSuppliesLast
        if !known { timingMode = .unknown }
        else if description?.nilIfBlank?.lowercased() == "all night" || description?.nilIfBlank == nil { timingMode = .allNight }
        else { timingMode = .specific }
    }

    private var shape: DealShape {
        let kind = priceMode == .single ? "absolute" : (priceMode == .range ? "range" : "relative")
        return .init(
            canonicalFamilyId: familyID,
            category: category,
            discountPercent: priceMode == .percent ? Double(percent) : nil,
            displayName: name.trimmingCharacters(in: .whitespacesAndNewlines),
            priceCents: priceMode == .single ? low : nil,
            priceHighCents: priceMode == .range ? max(low, high) : nil,
            priceKind: kind,
            priceLowCents: priceMode == .range ? low : nil,
            servingFormat: serving.nilIfBlank,
            timingDescription: timingMode == .specific ? timing.nilIfBlank : nil,
            timingKnown: timingMode != .unknown,
            unit: unit.nilIfBlank,
            whileSuppliesLast: whileSuppliesLast
        )
    }

    private func submit() {
        submitting = true
        Task {
            let now = Date.now, id = UUID().uuidString
            let location = environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil
            let request = DealEvidenceRequest(
                action: seed.action,
                clientPlatform: "ios",
                entryPoint: "deal_composer",
                location: location,
                observedAt: now,
                serviceDateLocal: ServiceNight.serviceDate(containing: now),
                submissionId: id,
                submittedDealShape: shape,
                targetDealId: seed.deal?.id,
                vantagePoint: .unknown,
                venueId: seed.venue.id
            )
            let outcome = await environment.submitDeal(request)
            submitting = false
            if outcome == .failed { error = outcome.dealNotice(for: seed.action); Haptics.warning() }
            else { environment.globalNotice = outcome.dealNotice(for: seed.action); Haptics.success(); dismiss() }
        }
    }
}
