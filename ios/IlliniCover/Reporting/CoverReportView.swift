import SwiftUI

@MainActor
@Observable
final class CoverReportModel {
    static let holdRepeatIntervalsMilliseconds = [220, 180, 140, 110, 90]
    var priceCents: Int
    var includeCover: Bool
    var priceTouched: Bool
    var manualEntry = ""
    var isEditingPrice = false
    var vantage: VantagePoint = .unknown
    var vibes: [VibeDimension: String] = [:]
    var includeLocation: Bool
    var isSubmitting = false
    var errorMessage: String?
    private let wasPrefilled: Bool
    private let rawPrefilledCents: Int?

    init(seed: CoverReportSeed, includeLocation: Bool) {
        priceCents = CoverPrice.normalizedReportCents(seed.initialPriceCents ?? 0)
        includeCover = seed.initialPriceCents != nil
        priceTouched = false
        wasPrefilled = seed.initialPriceCents != nil
        rawPrefilledCents = seed.initialPriceCents
        self.includeLocation = includeLocation
    }

    var hasObservation: Bool {
        hasCoverObservation || !reportableVibes.isEmpty
    }

    var canDecreasePrice: Bool { !includeCover || priceCents > 0 }
    var canIncreasePrice: Bool { !includeCover || priceCents < 7_000 }

    var reportableVibes: [VibeDimension: String] {
        vibes.filter { dimension, _ in
            switch (vantage, dimension) {
            case (.inside, .lineLength), (.inside, .lineSpeed), (.outside, .crowdLevel): false
            default: true
            }
        }
    }

    var coverPriceFooterText: String {
        if !priceTouched,
           let rawPrefilledCents,
           rawPrefilledCents != priceCents {
            return "The displayed cover was \(CoverPrice.currency(rawPrefilledCents)). Reports use $5 steps, so Submit will report \(CoverPrice.currency(priceCents))."
        }
        if includeCover && !priceTouched {
            return "Submit includes the displayed price. Edit it only if it is different."
        }
        return "Choose the cover you see."
    }

    private var draftCoverPriceCents: Int? {
        includeCover ? priceCents : nil
    }

    private var hasCoverObservation: Bool {
        draftCoverPriceCents != nil
    }

    private var manualPriceCents: Int? {
        let normalized = manualEntry
            .replacingOccurrences(of: "$", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return nil }
        let parts = normalized.split(separator: ".", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count <= 2,
              parts.contains(where: { !$0.isEmpty }),
              parts.allSatisfy({ part in part.allSatisfy { $0 >= "0" && $0 <= "9" } })
        else { return nil }
        guard let dollars = Decimal(string: normalized, locale: Locale(identifier: "en_US_POSIX")) else {
            // Foundation.Decimal has finite precision. A syntactically valid
            // integer whose magnitude exceeds that precision is necessarily
            // above the $70 domain ceiling and can be clamped without ever
            // narrowing an infinite floating-point value to Int.
            let integer = String(parts[0]).drop(while: { $0 == "0" })
            return integer.count > 2 ? 7_000 : nil
        }
        guard dollars >= 0 else { return nil }
        // Clamp in Decimal space before converting. An arbitrarily long pasted
        // value must behave like an over-limit draft, not trap while narrowing
        // a non-finite or out-of-range Double to Int.
        let boundedDollars = min(dollars, Decimal(70))
        let cents = NSDecimalNumber(decimal: boundedDollars * 100).intValue
        return CoverPrice.normalizedReportCents(cents)
    }

    func adjustPrice(by cents: Int) {
        cancelManualEntry()
        // Clearing is a real unknown state. The next + starts at $5 and the
        // next - starts at $0; it must never resurrect the hidden old value.
        let base = includeCover ? priceCents : (cents > 0 ? 0 : 500)
        priceCents = min(7_000, max(0, base + cents))
        includeCover = true
        priceTouched = true
    }

    func choosePrice(_ cents: Int) {
        cancelManualEntry()
        priceCents = cents
        includeCover = true
        priceTouched = true
        Haptics.selection()
    }

    func clearCover() {
        manualEntry = ""
        isEditingPrice = false
        includeCover = false
        priceTouched = false
    }

    func selectVantage(_ value: VantagePoint) {
        vantage = value
        // Hidden observations must not survive progressive disclosure. A user
        // who changes location context can add the field again if they later
        // return to a compatible vantage.
        switch value {
        case .inside:
            vibes.removeValue(forKey: .lineLength)
            vibes.removeValue(forKey: .lineSpeed)
        case .outside:
            vibes.removeValue(forKey: .crowdLevel)
        case .unknown:
            break
        }
    }

    @discardableResult
    func commitManualEntry() -> Bool {
        let normalized = manualEntry.trimmingCharacters(in: .whitespacesAndNewlines)
        if normalized.isEmpty || normalized == "." {
            clearCover()
            errorMessage = nil
            return true
        }
        guard let manualPriceCents else {
            errorMessage = "Enter a valid dollar amount, such as 10 or 12.50."
            return false
        }
        priceCents = manualPriceCents
        includeCover = true
        priceTouched = true
        manualEntry = ""
        isEditingPrice = false
        errorMessage = nil
        return true
    }

    func beginManualEntry() {
        manualEntry = includeCover ? String(format: "%.0f", Double(priceCents) / 100) : ""
        isEditingPrice = true
        errorMessage = nil
    }

    func cancelManualEntry() {
        manualEntry = ""
        isEditingPrice = false
        errorMessage = nil
    }

    @discardableResult
    func preparePriceForSubmission() -> Bool {
        !isEditingPrice
    }

    func submit(seed: CoverReportSeed, environment: AppEnvironment) async -> SubmissionOutcome? {
        guard environment.canSubmitReports else {
            errorMessage = APIClientError.reportingPausedForAccountLinkConflict.localizedDescription
            environment.globalNotice = AppEnvironment.accountLinkConflictNotice
            return .failed
        }
        guard !isSubmitting, !isEditingPrice, hasObservation else { return nil }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        let location = includeLocation ? await environment.location.locationForSubmission() : nil
        let request = CoverSubmissionRequest(
            submissionId: UUID().uuidString,
            venueId: seed.venue.id,
            observedAt: .now,
            vantagePoint: vantage,
            location: location,
            cover: hasCoverObservation ? CoverObservationRequest(
                priceCents: priceCents,
                interaction: seed.interaction,
                displayedDecisionId: seed.decision.decisionId,
                pricePrefilled: wasPrefilled,
                priceTouched: priceTouched
            ) : nil,
            vibes: reportableVibes.map { VibeObservationRequest(dimension: $0.key, value: $0.value) },
            entryPoint: "report_sheet_\(seed.interaction.rawValue)"
        )

        do {
            _ = try await environment.api.submitCover(request)
            return .sent
        } catch let error as APIClientError where error.isRetryableSubmissionFailure || error.isUnauthorized {
            do {
                try await environment.outbox.enqueue(id: request.submissionId, kind: .cover, observedAt: request.observedAt, value: request)
                return .queued
            } catch {
                errorMessage = "The report could not be saved. Please try again."
                return .failed
            }
        } catch {
            errorMessage = error.localizedDescription
            return .failed
        }
    }
}

enum CoverHoldRepeatHapticPolicy {
    static let minimumInterval: Duration = .milliseconds(140)

    static func shouldEmit(now: ContinuousClock.Instant, last: ContinuousClock.Instant?) -> Bool {
        guard let last else { return true }
        return last.duration(to: now) >= minimumInterval
    }
}

struct CoverReportHeaderPresentation: Equatable {
    enum Tone: Equatable { case accent, right, wrong }

    let title: String
    let venueName: String
    let systemImage: String
    let tone: Tone

    static func make(interaction: CoverInteraction, venueName: String) -> CoverReportHeaderPresentation {
        switch interaction {
        case .confirm, .quickConfirm:
            .init(title: "Confirm", venueName: venueName, systemImage: "checkmark.circle.fill", tone: .right)
        case .correct:
            .init(title: "Adjust", venueName: venueName, systemImage: "wrench.and.screwdriver.fill", tone: .wrong)
        case .direct, .manual:
            .init(title: "Report", venueName: venueName, systemImage: "paperplane.fill", tone: .accent)
        }
    }
}

struct CoverReportView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let seed: CoverReportSeed
    @State private var model: CoverReportModel
    @State private var detent: PresentationDetent = .fraction(0.7)
    @State private var showHighPriceAlert = false
    @State private var successText: String?
    @FocusState private var manualPriceFocused: Bool

    init(seed: CoverReportSeed) {
        self.seed = seed
        _model = State(initialValue: CoverReportModel(seed: seed, includeLocation: false))
    }

    private var header: CoverReportHeaderPresentation {
        .make(interaction: seed.interaction, venueName: seed.venue.name)
    }

    private var headerColor: Color {
        switch header.tone {
        case .accent: ICTheme.accent
        case .right: ICTheme.right
        case .wrong: ICTheme.wrong
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 12) {
                        if model.isEditingPrice {
                            HStack(spacing: 8) {
                                Text("$")
                                    .font(.system(size: 40, weight: .bold, design: .rounded))
                                TextField("0", text: $model.manualEntry)
                                    .keyboardType(.decimalPad)
                                    .focused($manualPriceFocused)
                                    .font(.system(size: 40, weight: .bold, design: .rounded).monospacedDigit())
                                    .multilineTextAlignment(.center)
                                    .textFieldStyle(.plain)
                                    .frame(minWidth: 96, maxWidth: 140)
                                    .padding(.horizontal, 8)
                                    .padding(.bottom, 6)
                                    .overlay(alignment: .bottom) { Divider() }
                                    .accessibilityLabel("Enter cover price")
                                    .accessibilityIdentifier("cover-price-editor")
                            }
                            Text("Entered prices are rounded to the nearest $5.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                            HStack(spacing: 24) {
                                Button("Cancel", role: .cancel) {
                                    model.cancelManualEntry()
                                    manualPriceFocused = false
                                }
                                .foregroundStyle(.secondary)
                                Button("Done") {
                                    if model.commitManualEntry() { manualPriceFocused = false }
                                }
                                .foregroundStyle(ICTheme.accent)
                                .accessibilityIdentifier("cover-price-done")
                            }
                            .font(.subheadline.weight(.semibold))
                        } else {
                            HStack(spacing: 16) {
                                HoldRepeatPriceButton(
                                    systemImage: "minus",
                                    accessibilityLabel: "Decrease cover by five dollars",
                                    disabled: !model.canDecreasePrice,
                                    action: { model.adjustPrice(by: -500) }
                                )
                                Button {
                                    model.beginManualEntry()
                                    manualPriceFocused = true
                                } label: {
                                    Text(model.includeCover ? CoverPrice.currency(model.priceCents) : "--")
                                        .font(.system(
                                            size: model.includeCover && model.priceCents >= 7_000 ? 46 : 56,
                                            weight: .bold,
                                            design: .rounded
                                        ))
                                        .foregroundStyle(model.includeCover ? .primary : .secondary)
                                        .monospacedDigit()
                                        .frame(width: 128)
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Enter cover price manually")
                                .accessibilityValue(model.includeCover ? CoverPrice.currency(model.priceCents) : "Don't know")
                                .accessibilityIdentifier("cover-price-manual")
                                HoldRepeatPriceButton(
                                    systemImage: "plus",
                                    accessibilityLabel: "Increase cover by five dollars",
                                    disabled: !model.canIncreasePrice,
                                    action: { model.adjustPrice(by: 500) }
                                )
                            }
                            .frame(maxWidth: .infinity)

                            Button("Clear / Don’t Know") { model.clearCover() }
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(model.includeCover ? ICTheme.accent : .secondary)
                                .disabled(!model.includeCover)
                                .accessibilityIdentifier("cover-price-clear")

                            HStack(spacing: 8) {
                                ForEach([0, 500, 1_000, 2_000], id: \.self) { cents in
                                    let selected = model.includeCover && model.priceCents == cents
                                    Button(CoverPrice.currency(cents)) { model.choosePrice(cents) }
                                        .buttonStyle(CoverQuickPriceButtonStyle(selected: selected))
                                        .accessibilityLabel(cents == 0 ? "Set cover price to no cover" : "Set cover price to \(cents / 100) dollars")
                                        .accessibilityAddTraits(selected ? .isSelected : [])
                                        .accessibilityIdentifier("cover-quick-\(cents)")
                                }
                            }
                        }
                    }
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity)
                } footer: {
                    if !model.isEditingPrice {
                        Text(model.coverPriceFooterText)
                    }
                }
                .listRowBackground(Rectangle().fill(.regularMaterial))

                if !model.isEditingPrice {
                    Section("Where are you?") {
                        Picker("Vantage point", selection: Binding(
                            get: { model.vantage },
                            set: { model.selectVantage($0) }
                        )) {
                            ForEach(VantagePoint.allCases, id: \.self) { Text($0.label).tag($0) }
                        }
                        .pickerStyle(.segmented)
                    }

                    vibeSection

                    Section {
                        Toggle("Include Location", isOn: $model.includeLocation)
                    } footer: {
                        Text("A nearby location check gives this report stronger context. Location is checked only while submitting.")
                    }
                }

                if let error = model.errorMessage {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(model.isSubmitting) }
                ToolbarItem(placement: .principal) {
                    VStack(spacing: 1) {
                        HStack(spacing: 6) {
                            Image(systemName: header.systemImage)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(headerColor)
                            Text(header.title)
                                .font(.headline)
                        }
                        Text(header.venueName)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(header.title), \(header.venueName)")
                    .accessibilityIdentifier("cover-report-header")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.isSubmitting ? "Submitting…" : "Submit") {
                        guard model.preparePriceForSubmission() else {
                            Haptics.warning()
                            manualPriceFocused = true
                            return
                        }
                        if model.includeCover && model.priceCents > 4_000 { showHighPriceAlert = true }
                        else { submit() }
                    }
                    .disabled(!environment.canSubmitReports || !model.hasObservation || model.isEditingPrice || model.isSubmitting)
                    .accessibilityIdentifier("cover-report-submit")
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") {
                        if model.commitManualEntry() { manualPriceFocused = false }
                    }
                    .accessibilityIdentifier("cover-price-keyboard-done")
                }
            }
        }
        .onAppear { model.includeLocation = environment.settings.includeLocation }
        .presentationDetents([.fraction(0.4), .fraction(0.7), .large], selection: $detent)
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(model.isSubmitting)
        .alert("Report \(CoverPrice.currency(model.priceCents))?", isPresented: $showHighPriceAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Report \(CoverPrice.currency(model.priceCents))") { submit() }
        } message: {
            Text("That is an unusually high cover. Please double-check that it is \(CoverPrice.currency(model.priceCents)).")
        }
        .overlay {
            if let successText {
                ReportSuccessOverlay(text: successText, animate: !reduceMotion)
                    .transition(.opacity.combined(with: .scale(scale: 0.92)))
            }
        }
    }

    @ViewBuilder
    private var vibeSection: some View {
        Section("Optional conditions") {
            if model.vantage != .inside {
                VibePicker(title: "Line length", values: ["short", "medium", "long"], selection: vibeBinding(.lineLength))
                VibePicker(title: "Line speed", values: ["slow", "normal", "fast"], selection: vibeBinding(.lineSpeed))
            }
            if model.vantage != .outside {
                VibePicker(title: "Crowd", values: ["quiet", "busy", "packed"], selection: vibeBinding(.crowdLevel))
            }
        }
    }

    private func vibeBinding(_ dimension: VibeDimension) -> Binding<String?> {
        Binding(
            get: { model.vibes[dimension] },
            set: { value in model.vibes[dimension] = value }
        )
    }

    private func submit() {
        Task {
            guard let outcome = await model.submit(seed: seed, environment: environment) else { return }
            guard outcome != .failed else {
                Haptics.warning()
                return
            }
            if outcome == .sent { Haptics.success() } else { Haptics.selection() }
            withAnimation(reduceMotion ? nil : .spring(duration: 0.35)) {
                successText = outcome.coverNotice
            }
            try? await Task.sleep(for: .milliseconds(900))
            dismiss()
        }
    }
}

private struct HoldRepeatPriceButton: View {
    let systemImage: String
    let accessibilityLabel: String
    let disabled: Bool
    let action: () -> Void
    @State private var repeatTask: Task<Void, Never>?
    @State private var didRepeat = false
    @State private var lastHapticInstant: ContinuousClock.Instant?

    var body: some View {
        Button {
            if didRepeat {
                didRepeat = false
            } else {
                performStep()
            }
        } label: {
            Image(systemName: systemImage)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(ICTheme.accent)
                .frame(width: 44, height: 44)
                .background(Color(uiColor: .tertiarySystemFill), in: .circle)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(accessibilityLabel)
        .onLongPressGesture(minimumDuration: 0.325, maximumDistance: 44, pressing: { pressing in
            if !pressing { stopRepeating() }
        }) {
            guard !disabled else { return }
            didRepeat = true
            performStep()
            repeatTask = Task { @MainActor in
                var index = 0
                while !Task.isCancelled {
                    let intervals = CoverReportModel.holdRepeatIntervalsMilliseconds
                    try? await Task.sleep(for: .milliseconds(intervals[index]))
                    guard !Task.isCancelled else { return }
                    performStep()
                    index = min(index + 1, intervals.count - 1)
                }
            }
        }
        .onDisappear { stopRepeating() }
    }

    private func stopRepeating() {
        repeatTask?.cancel()
        repeatTask = nil
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(120))
            didRepeat = false
            lastHapticInstant = nil
        }
    }

    private func performStep() {
        action()
        let now = ContinuousClock().now
        guard CoverHoldRepeatHapticPolicy.shouldEmit(now: now, last: lastHapticInstant) else { return }
        lastHapticInstant = now
        Haptics.selection()
    }
}

private struct CoverQuickPriceButtonStyle: ButtonStyle {
    let selected: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(selected ? .white : .secondary)
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(
                selected ? ICTheme.accent : Color(uiColor: .tertiarySystemFill),
                in: .rect(cornerRadius: 12, style: .continuous)
            )
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

private struct VibePicker: View {
    let title: String
    let values: [String]
    @Binding var selection: String?

    var body: some View {
        Picker(title, selection: $selection) {
            Text("Don’t know").tag(String?.none)
            ForEach(values, id: \.self) { Text($0.capitalized).tag(Optional($0)) }
        }
    }
}

struct ReportSuccessOverlay: View {
    let text: String
    let animate: Bool
    @State private var visible = false

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(ICTheme.right)
                .symbolEffect(.bounce, value: visible)
            Text(text).font(.headline).multilineTextAlignment(.center)
        }
        .padding(28)
        .background(.regularMaterial, in: .rect(cornerRadius: 22))
        .padding()
        .onAppear { if animate { visible.toggle() } }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}
