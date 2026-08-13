import Foundation
import Observation
import SwiftUI

enum DealPriceMode: String, CaseIterable, Identifiable {
    case single = "Single"
    case range = "Range"
    case percentOff = "% off"
    var id: String { rawValue }
}

enum TimingKind: String, CaseIterable {
    case allNight = "All night"
    case untilSoldOut = "Until sold out"
    case unknown = "Unknown"
    case before = "Before"
    case after = "After"
    case between = "Between"
}

struct DealComposerHeaderPresentation: Equatable {
    enum Tone: Equatable { case accent, right, wrong }

    let title: String
    let subtitle: String
    let systemImage: String
    let tone: Tone

    static func make(seed: DealComposerSeed) -> DealComposerHeaderPresentation {
        let title: String
        let systemImage: String
        let tone: Tone
        switch seed.mode {
        case .add:
            title = "Add Deal"
            systemImage = "plus"
            tone = .accent
        case .confirm:
            title = "Confirm"
            systemImage = "checkmark"
            tone = .right
        case .deny:
            title = "Wrong"
            systemImage = "xmark"
            tone = .wrong
        case .review:
            title = "Review"
            systemImage = "info.circle"
            tone = .accent
        }
        return .init(
            title: title,
            subtitle: "\(seed.venue.name) • \(serviceDateLabel(seed.serviceDate))",
            systemImage: systemImage,
            tone: tone
        )
    }

    static func serviceDateLabel(_ serviceDate: String) -> String {
        let components = serviceDate.split(separator: "-").compactMap { Int($0) }
        guard components.count == 3 else { return serviceDate }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Chicago")!
        guard let date = calendar.date(from: DateComponents(
            timeZone: calendar.timeZone,
            year: components[0],
            month: components[1],
            day: components[2],
            hour: 12
        )) else { return serviceDate }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "EEEE, MMM d"
        return formatter.string(from: date)
    }
}

@MainActor
@Observable
final class DealComposerModel {
    enum NameCommit: Equatable {
        case suggestion(DealSuggestion)
        case custom(String)
    }

    var category: DealCategory
    var name: String
    var canonicalFamilyId: String?
    var priceMode: DealPriceMode = .single
    var singlePriceText = ""
    var lowPriceText = ""
    var highPriceText = ""
    var percentOff = 50
    var servingFormat: String?
    var unit: String?
    var customServing = ""
    var timingKind: TimingKind = .unknown
    var startTime = Date.now
    var endTime = Date.now.addingTimeInterval(3_600)
    var priceExpanded = false
    var isSubmitting = false
    var errorMessage: String?
    var appliedInfoFlash = false
    var appliedPriceFlash = false
    private var priceEditSnapshot: PriceEditSnapshot?

    private struct PriceEditSnapshot {
        let mode: DealPriceMode
        let single: String
        let low: String
        let high: String
        let percent: Int
    }

    init(seed: DealComposerSeed) {
        let deal = seed.deal
        category = deal?.category ?? .drink
        name = deal?.name ?? ""
        canonicalFamilyId = deal?.familyId
        servingFormat = deal?.servingFormat ?? (deal == nil ? "Each" : nil)
        unit = deal?.unit ?? (deal == nil ? "Each" : nil)
        if let deal {
            apply(price: deal.price)
            apply(timing: deal.timing)
        }
    }

    var price: DealPrice? {
        switch priceMode {
        case .single:
            guard let cents = cents(singlePriceText) else { return nil }
            return .single(cents)
        case .range:
            guard let low = cents(lowPriceText), let high = cents(highPriceText), low <= high else { return nil }
            return .range(low, high)
        case .percentOff:
            return .percentOff(percentOff)
        }
    }

    var timing: DealTiming {
        let formatter = DateFormatter.localTime
        return switch timingKind {
        case .allNight: .allNight
        case .untilSoldOut: .untilSoldOut
        case .unknown: .unknown
        case .before: .before(formatter.string(from: endTime))
        case .after: .after(formatter.string(from: startTime))
        case .between: .between(formatter.string(from: startTime), formatter.string(from: endTime))
        }
    }

    var isValid: Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && price != nil }
    var isEditingPrice: Bool { priceEditSnapshot != nil }
    var serving: String? { Deal.presentServing(format: servingFormat, unit: unit) }

    static func nameCommit(query: String, matches: [DealSuggestion]) -> NameCommit? {
        if let first = matches.first { return .suggestion(first) }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : .custom(trimmed)
    }

    func chooseQuickPrice(dollars: Int) {
        cancelPriceEditing()
        priceMode = .single
        singlePriceText = String(dollars)
        Haptics.selection()
    }

    func setServingPreset(_ value: String, category: DealCategory? = nil) {
        servingFormat = value
        unit = value
        customServing = ""
        if let category { self.category = category }
        Haptics.selection()
    }

    func setCustomServing() {
        servingFormat = nil
        unit = nil
        customServing = ""
        Haptics.selection()
    }

    func apply(suggestion: Deal) {
        cancelPriceEditing()
        let infoChanged = category != suggestion.category
            || name != suggestion.name
            || canonicalFamilyId != suggestion.familyId
            || servingFormat != suggestion.servingFormat
            || unit != suggestion.unit
            || timing != suggestion.timing
        let priceChanged = price != suggestion.price
        category = suggestion.category
        name = suggestion.name
        canonicalFamilyId = suggestion.familyId
        servingFormat = suggestion.servingFormat
        unit = suggestion.unit
        customServing = ""
        apply(price: suggestion.price)
        apply(timing: suggestion.timing)
        appliedInfoFlash = infoChanged
        appliedPriceFlash = priceChanged
        Haptics.selection()
        Task {
            try? await Task.sleep(for: .milliseconds(550))
            appliedInfoFlash = false
            appliedPriceFlash = false
        }
    }

    func beginPriceEditing() {
        guard priceEditSnapshot == nil else { return }
        priceEditSnapshot = PriceEditSnapshot(
            mode: priceMode,
            single: singlePriceText,
            low: lowPriceText,
            high: highPriceText,
            percent: percentOff
        )
        errorMessage = nil
    }

    func cancelPriceEditing() {
        guard let snapshot = priceEditSnapshot else { return }
        priceMode = snapshot.mode
        singlePriceText = snapshot.single
        lowPriceText = snapshot.low
        highPriceText = snapshot.high
        percentOff = snapshot.percent
        priceEditSnapshot = nil
        errorMessage = nil
    }

    @discardableResult
    func commitPriceEditing() -> Bool {
        guard priceEditSnapshot != nil else { return true }
        switch priceMode {
        case .single:
            guard let cents = cents(singlePriceText) else { return priceValidationFailed() }
            singlePriceText = Self.dollarText(cents)
        case .range:
            guard let low = cents(lowPriceText), let high = cents(highPriceText), low <= high else {
                return priceValidationFailed("Enter a valid range with the minimum no greater than the maximum.")
            }
            lowPriceText = Self.dollarText(low)
            highPriceText = Self.dollarText(high)
        case .percentOff:
            percentOff = min(100, max(5, percentOff))
        }
        priceEditSnapshot = nil
        errorMessage = nil
        return true
    }

    func adjustSinglePrice(by centsDelta: Int) {
        singlePriceText = adjustedPrice(singlePriceText, by: centsDelta)
    }

    func adjustLowPrice(by centsDelta: Int) {
        lowPriceText = adjustedPrice(lowPriceText, by: centsDelta)
    }

    func adjustHighPrice(by centsDelta: Int) {
        highPriceText = adjustedPrice(highPriceText, by: centsDelta)
    }

    func adjustPercent(by delta: Int) {
        percentOff = min(100, max(5, percentOff + delta))
    }

    func canAdjust(_ text: String, by delta: Int) -> Bool {
        let current = cents(text) ?? 0
        return (0...10_000).contains(current + delta)
    }

    func canAdjustPercent(by delta: Int) -> Bool {
        (5...100).contains(percentOff + delta)
    }

    func submit(seed: DealComposerSeed, environment: AppEnvironment) async -> SubmissionOutcome? {
        guard environment.canSubmitReports else {
            errorMessage = APIClientError.reportingPausedForAccountLinkConflict.localizedDescription
            environment.globalNotice = AppEnvironment.accountLinkConflictNotice
            return .failed
        }
        let action: DealEvidenceAction = switch seed.mode {
        case .add: .addMissing
        case .confirm: .confirmPresent
        case .deny: .denyPresent
        case .review: .correct
        }
        guard !isSubmitting else { return nil }
        guard seed.serviceDate == ServiceNight.currentServiceDate else {
            errorMessage = "The service night changed while this form was open. Close it and refresh tonight’s deals."
            return .failed
        }
        let shape: SubmittedDealShape?
        if action == .denyPresent {
            // A denial is evidence about whether the target is running. It
            // deliberately carries no replacement shape and therefore never
            // depends on an editable name or price draft.
            shape = nil
        } else {
            guard let price, isValid else { return nil }
            shape = SubmittedDealShape(
                canonicalFamilyId: canonicalFamilyId,
                category: category,
                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                price: price,
                servingFormat: (serving == nil ? customServing : servingFormat)?.nilIfBlank,
                unit: (serving == nil ? customServing : unit)?.nilIfBlank,
                timing: timing
            )
        }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        let location = environment.settings.includeLocation ? await environment.location.locationForSubmission() : nil
        let request = DealEvidenceRequest(
            submissionId: UUID().uuidString,
            venueId: seed.venue.id,
            observedAt: .now,
            action: action,
            targetDealId: seed.deal?.id,
            targetPredictionId: seed.deal?.predictionId,
            // Public deal rows expose the latest evidence event, not whether
            // it belongs to this actor. Cross-actor supersession would erase
            // another reporter's lineage, so corrections target the public
            // deal/prediction and omit supersedesEventId.
            supersedesEventId: nil,
            submittedDeal: shape,
            serviceDateLocal: seed.serviceDate,
            targetLocalDateTime: nil,
            entryPoint: "deal_composer_\(seed.mode.rawValue)",
            location: location
        )
        do {
            _ = try await environment.api.submitDeal(request)
            return .sent
        } catch let error as APIClientError where error.isRetryableSubmissionFailure || error.isUnauthorized {
            do {
                try await environment.outbox.enqueue(id: request.submissionId, kind: .deal, observedAt: request.observedAt, value: request)
                return .queued
            } catch {
                errorMessage = "The update could not be saved. Please try again."
                return .failed
            }
        } catch {
            errorMessage = error.localizedDescription
            return .failed
        }
    }

    private func cents(_ text: String) -> Int? {
        guard let value = Decimal(string: text.replacingOccurrences(of: "$", with: "")), value >= 0, value <= 100 else { return nil }
        return NSDecimalNumber(decimal: value * 100).intValue
    }

    private func adjustedPrice(_ text: String, by centsDelta: Int) -> String {
        let current = cents(text) ?? 0
        return Self.dollarText(min(10_000, max(0, current + centsDelta)))
    }

    private func priceValidationFailed(_ message: String = "Enter a valid price from $0 to $100.") -> Bool {
        errorMessage = message
        return false
    }

    private func apply(price: DealPrice) {
        switch price {
        case .single(let cents):
            priceMode = .single; singlePriceText = Self.dollarText(cents)
        case .range(let low, let high):
            priceMode = .range; lowPriceText = Self.dollarText(low); highPriceText = Self.dollarText(high)
        case .percentOff(let percent):
            priceMode = .percentOff; percentOff = percent
        case .unknown:
            priceMode = .single; singlePriceText = ""
        }
    }

    private func apply(timing: DealTiming) {
        switch timing {
        case .allNight: timingKind = .allNight
        case .untilSoldOut: timingKind = .untilSoldOut
        case .unknown: timingKind = .unknown
        case .before(let value):
            timingKind = .before
            endTime = DateFormatter.localTime.date(from: value) ?? endTime
        case .after(let value):
            timingKind = .after
            startTime = DateFormatter.localTime.date(from: value) ?? startTime
        case .between(let start, let end):
            timingKind = .between
            startTime = DateFormatter.localTime.date(from: start) ?? startTime
            endTime = DateFormatter.localTime.date(from: end) ?? endTime
        }
    }

    private static func dollarText(_ cents: Int) -> String {
        cents.isMultiple(of: 100) ? String(cents / 100) : String(format: "%.2f", Double(cents) / 100)
    }
}

enum DealPriceHoldRepeatPolicy {
    static let intervalsMilliseconds = [220, 180, 140, 110, 90]
    static let minimumHapticInterval: Duration = .milliseconds(140)

    static func shouldEmitHaptic(now: ContinuousClock.Instant, last: ContinuousClock.Instant?) -> Bool {
        guard let last else { return true }
        return last.duration(to: now) >= minimumHapticInterval
    }
}

@MainActor
@Observable
final class DealSuggestionSearchModel {
    var matches: [DealSuggestion] = []
    var isLoading = false
    var errorMessage: String?

    func load(query: String, venueID: String, api: any AppAPI) async {
        isLoading = true
        defer { isLoading = false }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            try? await Task.sleep(for: .milliseconds(180))
            guard !Task.isCancelled else { return }
        }
        do {
            matches = Array(try await api.dealSuggestions(query: trimmed, venueID: venueID).prefix(6))
            errorMessage = nil
        } catch {
            // Current slate rows are not historical suggestion receipts: they
            // may be predictions and carry no source/date metadata. Never turn
            // them into a fabricated "Seen here · today" fallback.
            matches = []
            errorMessage = "Past deal suggestions are unavailable. You can still enter a custom name."
        }
    }
}

struct DealComposerView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(\.dismiss) private var dismiss
    let seed: DealComposerSeed
    @State private var model: DealComposerModel
    @State private var isNameSearchPresented = false
    @State private var didAutoPresentNameSearch = false
    @State private var detent: PresentationDetent = .fraction(0.7)
    @State private var successText: String?
    @FocusState private var editingText: Bool
    @FocusState private var priceFocus: PriceFocus?

    private enum PriceFocus { case single, low, high }

    init(seed: DealComposerSeed) {
        self.seed = seed
        _model = State(initialValue: DealComposerModel(seed: seed))
    }

    private var header: DealComposerHeaderPresentation { .make(seed: seed) }

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
                if seed.mode == .deny {
                    Section {
                        Button("Not running tonight", role: .destructive) { submit() }
                            .disabled(model.isSubmitting)
                    } footer: {
                        Text("A denial adds evidence and never erases this deal’s history.")
                    }
                }

                Section {
                    Button {
                        isNameSearchPresented = true
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Deal").font(.caption).foregroundStyle(.secondary)
                                Text(model.name.isEmpty ? "Add a deal name" : model.name)
                                    .foregroundStyle(model.name.isEmpty ? .secondary : .primary)
                            }
                            Spacer()
                            Image(systemName: "chevron.up.chevron.down").foregroundStyle(.secondary)
                        }
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(model.appliedInfoFlash ? Color.orange.opacity(0.18) : ICTheme.card)
                    .animation(.easeOut(duration: 0.45), value: model.appliedInfoFlash)
                    .accessibilityHint("Opens searchable past deals and custom name entry")
                    HStack(spacing: 12) {
                        timingMenu
                        Divider()
                        servingMenu
                    }
                    if model.serving == nil { TextField("Serving details", text: $model.customServing).focused($editingText) }
                    if model.timingKind == .after || model.timingKind == .between {
                        DatePicker("Start time", selection: $model.startTime, displayedComponents: .hourAndMinute)
                            .datePickerStyle(.wheel)
                    }
                    if model.timingKind == .before || model.timingKind == .between {
                        DatePicker("End time", selection: $model.endTime, displayedComponents: .hourAndMinute)
                            .datePickerStyle(.wheel)
                    }
                } header: {
                    Text("Deal")
                } footer: {
                    Text("Unknown means the source did not establish timing; it does not mean all night.")
                }
                .listRowBackground(model.appliedInfoFlash ? Color.orange.opacity(0.18) : ICTheme.card)

                Section("Price") {
                    DisclosureGroup(isExpanded: $model.priceExpanded) {
                        Picker("Price type", selection: $model.priceMode) {
                            ForEach(DealPriceMode.allCases) { Text($0.rawValue).tag($0) }
                        }
                        .pickerStyle(.segmented)
                        priceEditor
                    } label: {
                        LabeledContent("Price", value: model.price?.displayText ?? "Choose a price")
                    }
                    if !model.priceExpanded {
                        HStack {
                            ForEach(1...5, id: \.self) { dollars in
                                Button("$\(dollars)") { model.chooseQuickPrice(dollars: dollars) }
                                    .buttonStyle(.bordered)
                                    .buttonBorderShape(.capsule)
                            }
                        }
                    }
                }
                .listRowBackground(model.appliedPriceFlash ? Color.orange.opacity(0.18) : ICTheme.card)

                if let error = model.errorMessage { Section { Text(error).foregroundStyle(.red) } }
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
                        Text(header.subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(header.title), \(header.subtitle)")
                    .accessibilityIdentifier("deal-composer-header")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.isSubmitting ? "Submitting…" : submitTitle) { submit() }
                        .disabled(!environment.canSubmitReports || !model.isValid || model.isEditingPrice || model.isSubmitting)
                        .accessibilityIdentifier("deal-submit")
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") {
                        if model.isEditingPrice {
                            if model.commitPriceEditing() { priceFocus = nil }
                        } else {
                            editingText = false
                        }
                    }
                }
            }
        }
        .presentationDetents([.fraction(0.4), .fraction(0.7), .large], selection: $detent)
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(model.isSubmitting)
        .onChange(of: priceFocus) { _, focused in
            if focused != nil { model.beginPriceEditing() }
        }
        .overlay {
            if isNameSearchPresented {
                DealNameSearchOverlay(
                    model: model,
                    venueID: seed.venue.id,
                    venueName: seed.venue.name,
                    onClose: { isNameSearchPresented = false }
                )
                .transition(.opacity)
                .zIndex(2)
            } else if let successText {
                ReportSuccessOverlay(text: successText, animate: true)
            }
        }
        .task {
            guard seed.mode == .add, seed.deal == nil, !didAutoPresentNameSearch else { return }
            didAutoPresentNameSearch = true
            await Task.yield()
            isNameSearchPresented = true
        }
    }

    private var servingMenu: some View {
        Menu {
            Button("Each") { model.setServingPreset("Each") }
            Menu("Drinks") {
                ForEach(["Can", "Bottle", "Pitcher", "Shot", "Pint", "Glass"], id: \.self) { value in
                    Button(value) { model.setServingPreset(value, category: .drink) }
                }
            }
            Menu("Food") {
                ForEach(["Order", "Basket", "Plate"], id: \.self) { value in
                    Button(value) { model.setServingPreset(value, category: .food) }
                }
            }
            Divider()
            Button("Other") { model.setCustomServing() }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text("Serving").font(.caption).foregroundStyle(.secondary)
                Text(model.serving ?? "Other").lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("deal-serving-menu")
    }

    private var timingMenu: some View {
        Menu {
            Button("All night") { model.timingKind = .allNight }
            Button("Until sold out") { model.timingKind = .untilSoldOut }
            Button("Unknown") { model.timingKind = .unknown }
            Menu("At a time") {
                Button("Before") { model.timingKind = .before }
                Button("After") { model.timingKind = .after }
                Button("Between") { model.timingKind = .between }
            }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text("Timing").font(.caption).foregroundStyle(.secondary)
                Text(model.timingKind.rawValue).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("deal-timing-menu")
    }

    @ViewBuilder
    private var priceEditor: some View {
        switch model.priceMode {
        case .single:
            priceStepper(
                title: "Price",
                text: $model.singlePriceText,
                focus: .single,
                decrease: { model.adjustSinglePrice(by: -100) },
                increase: { model.adjustSinglePrice(by: 100) },
                canDecrease: model.canAdjust(model.singlePriceText, by: -100),
                canIncrease: model.canAdjust(model.singlePriceText, by: 100)
            )
        case .range:
            priceStepper(
                title: "Minimum price",
                text: $model.lowPriceText,
                focus: .low,
                decrease: { model.adjustLowPrice(by: -100) },
                increase: { model.adjustLowPrice(by: 100) },
                canDecrease: model.canAdjust(model.lowPriceText, by: -100),
                canIncrease: model.canAdjust(model.lowPriceText, by: 100)
            )
            priceStepper(
                title: "Maximum price",
                text: $model.highPriceText,
                focus: .high,
                decrease: { model.adjustHighPrice(by: -100) },
                increase: { model.adjustHighPrice(by: 100) },
                canDecrease: model.canAdjust(model.highPriceText, by: -100),
                canIncrease: model.canAdjust(model.highPriceText, by: 100)
            )
        case .percentOff:
            VStack(spacing: 8) {
                Text("DISCOUNT")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                HStack(spacing: 14) {
                    DealPriceHoldRepeatButton(
                        systemImage: "minus.circle.fill",
                        accessibilityLabel: "Decrease discount",
                        disabled: !model.canAdjustPercent(by: -5),
                        action: { model.adjustPercent(by: -5) }
                    )
                    Text("\(model.percentOff)% off")
                        .font(.system(size: 30, weight: .bold, design: .rounded).monospacedDigit())
                        .frame(maxWidth: .infinity)
                    DealPriceHoldRepeatButton(
                        systemImage: "plus.circle.fill",
                        accessibilityLabel: "Increase discount",
                        disabled: !model.canAdjustPercent(by: 5),
                        action: { model.adjustPercent(by: 5) }
                    )
                }
            }
        }
        if model.isEditingPrice {
            HStack(spacing: 24) {
                Button("Cancel", role: .cancel) {
                    model.cancelPriceEditing()
                    priceFocus = nil
                }
                Button("Done") {
                    if model.commitPriceEditing() { priceFocus = nil }
                }
                .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func priceStepper(
        title: String,
        text: Binding<String>,
        focus: PriceFocus,
        decrease: @escaping () -> Void,
        increase: @escaping () -> Void,
        canDecrease: Bool,
        canIncrease: Bool
    ) -> some View {
        VStack(spacing: 8) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            HStack(spacing: 14) {
                DealPriceHoldRepeatButton(
                    systemImage: "minus.circle.fill",
                    accessibilityLabel: "Decrease \(title.lowercased())",
                    disabled: !canDecrease,
                    action: decrease
                )
                TextField(title, text: text)
                    .keyboardType(.decimalPad)
                    .focused($priceFocus, equals: focus)
                    .multilineTextAlignment(.center)
                    .font(.system(size: 30, weight: .bold, design: .rounded).monospacedDigit())
                    .onTapGesture { model.beginPriceEditing() }
                    .accessibilityHint("Enter an exact price up to 100 dollars")
                DealPriceHoldRepeatButton(
                    systemImage: "plus.circle.fill",
                    accessibilityLabel: "Increase \(title.lowercased())",
                    disabled: !canIncrease,
                    action: increase
                )
            }
        }
    }

    private var submitTitle: String {
        switch seed.mode {
        case .add: "Add"
        case .confirm: "Confirm"
        case .deny: "Mark Wrong"
        case .review: "Save"
        }
    }

    private func submit() {
        Task {
            guard let outcome = await model.submit(seed: seed, environment: environment) else { return }
            guard outcome != .failed else { Haptics.warning(); return }
            if outcome == .sent { Haptics.success() } else { Haptics.selection() }
            withAnimation(.snappy) {
                successText = outcome == .sent ? "Update submitted." : "Saved offline. We’ll send it when you reconnect."
            }
            try? await Task.sleep(for: .milliseconds(850))
            dismiss()
        }
    }
}

private struct DealPriceHoldRepeatButton: View {
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
                .font(.title2)
                .frame(minWidth: 44, minHeight: 44)
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
                    let intervals = DealPriceHoldRepeatPolicy.intervalsMilliseconds
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
        guard !disabled else {
            repeatTask?.cancel()
            return
        }
        action()
        let now = ContinuousClock().now
        guard DealPriceHoldRepeatPolicy.shouldEmitHaptic(now: now, last: lastHapticInstant) else { return }
        lastHapticInstant = now
        Haptics.selection()
    }
}

private struct DealNameSearchOverlay: View {
    @Environment(AppEnvironment.self) private var environment
    let model: DealComposerModel
    let venueID: String
    let venueName: String
    let onClose: () -> Void
    @State private var query: String
    @State private var searchModel = DealSuggestionSearchModel()
    @FocusState private var searchFocused: Bool

    init(
        model: DealComposerModel,
        venueID: String,
        venueName: String,
        onClose: @escaping () -> Void
    ) {
        self.model = model
        self.venueID = venueID
        self.venueName = venueName
        self.onClose = onClose
        _query = State(initialValue: model.name)
    }

    var body: some View {
        ZStack(alignment: .top) {
            Button(action: { close() }) {
                Color.black.opacity(0.22).ignoresSafeArea()
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close deal search")

            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search past deals…", text: $query)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .focused($searchFocused)
                        .submitLabel(.done)
                        .onSubmit(commitSearch)
                        .accessibilityIdentifier("deal-search-field")
                    if !query.isEmpty {
                        Button {
                            query = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .accessibilityLabel("Clear search")
                    }
                    Button(action: close) {
                        Image(systemName: "xmark")
                            .font(.body.weight(.semibold))
                            .frame(width: 32, height: 32)
                    }
                    .accessibilityLabel("Close deal search")
                    .accessibilityIdentifier("deal-search-close")
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)

                Divider()

                Text(DealNameSearchCopy.sectionTitle(query: query, venueName: venueName))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .tracking(0.2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)

                ScrollView {
                    LazyVStack(spacing: 0) {
                        if let loadError = searchModel.errorMessage, searchModel.matches.isEmpty && !searchModel.isLoading {
                            Text(loadError)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14)
                        } else if searchModel.matches.isEmpty && !searchModel.isLoading {
                            Text(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                 ? "No recent deals yet. Type a custom deal name."
                                 : "No matching past deals.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14)
                        }

                        ForEach(Array(searchModel.matches.enumerated()), id: \.element.id) { index, suggestion in
                            Button {
                                model.apply(suggestion: suggestion.deal)
                                close()
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                                        Text(suggestion.deal.price.displayText)
                                            .font(.subheadline.bold().monospacedDigit())
                                            .fixedSize()
                                        highlightedName(suggestion.deal.name)
                                            .font(.subheadline.weight(.medium))
                                            .lineLimit(1)
                                    }
                                    if let detail = suggestionDetail(suggestion.deal) {
                                        Text(detail)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    Text(suggestion.provenanceText)
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                    if let match = suggestion.matchContextText {
                                        Text(match)
                                            .font(.caption2)
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 10)
                                .overlay(alignment: .leading) {
                                    if index == 0 {
                                        Rectangle()
                                            .fill(ICTheme.accent)
                                            .frame(width: 3)
                                    }
                                }
                                .contentShape(.rect)
                            }
                            .buttonStyle(.plain)
                            if index < searchModel.matches.count - 1 { Divider().padding(.leading, 14) }
                        }

                        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
                        if !trimmed.isEmpty {
                            Divider()
                            Button {
                                model.name = trimmed
                                model.canonicalFamilyId = nil
                                close()
                            } label: {
                                HStack {
                                    Image(systemName: "text.cursor")
                                    Text("Use custom name “\(trimmed)”")
                                        .lineLimit(2)
                                    Spacer(minLength: 0)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14)
                                .contentShape(.rect)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxHeight: 390)
            }
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .shadow(color: .black.opacity(0.18), radius: 18, y: 8)
            .padding(.horizontal, 12)
            .padding(.top, 12)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Deal name search")
        }
        .task(id: query) { await loadSuggestions() }
        .task {
            try? await Task.sleep(for: .milliseconds(120))
            searchFocused = true
        }
    }

    private func commitSearch() {
        switch DealComposerModel.nameCommit(query: query, matches: searchModel.matches) {
        case .suggestion(let suggestion):
            model.apply(suggestion: suggestion.deal)
            close()
        case .custom(let name):
            model.name = name
            model.canonicalFamilyId = nil
            close()
        case nil:
            break
        }
    }

    private func close() {
        searchFocused = false
        onClose()
    }

    private func suggestionDetail(_ deal: Deal) -> String? {
        let detail = [deal.timing == .unknown ? nil : deal.timing.displayText, deal.serving]
            .compactMap { $0 }
            .joined(separator: " · ")
        return detail.isEmpty ? nil : detail
    }

    private func highlightedName(_ name: String) -> Text {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              let range = name.range(of: trimmed, options: [.caseInsensitive, .diacriticInsensitive]) else {
            return Text(name).foregroundColor(.primary)
        }
        return Text(String(name[..<range.lowerBound])).foregroundColor(.primary)
            + Text(String(name[range])).foregroundColor(ICTheme.accent).bold()
            + Text(String(name[range.upperBound...])).foregroundColor(.primary)
    }

    @MainActor
    private func loadSuggestions() async {
        await searchModel.load(query: query, venueID: venueID, api: environment.api)
    }
}

enum DealNameSearchCopy {
    static func sectionTitle(query: String, venueName: String) -> String {
        query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Recent deals · \(venueName)"
            : "Matches"
    }
}

enum ServiceNight {
    static var currentServiceDate: String { serviceDate(containing: .now) }

    static func serviceDate(containing date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Chicago")!
        let local = calendar.dateComponents([.year, .month, .day, .hour], from: date)
        let serviceDay: Date
        if (local.hour ?? 0) < 5 {
            let localMidnight = calendar.date(from: DateComponents(
                timeZone: calendar.timeZone,
                year: local.year,
                month: local.month,
                day: local.day
            ))!
            serviceDay = calendar.date(byAdding: .day, value: -1, to: localMidnight)!
        } else {
            serviceDay = date
        }
        let components = calendar.dateComponents([.year, .month, .day], from: serviceDay)
        return String(format: "%04d-%02d-%02d", components.year!, components.month!, components.day!)
    }
}

private extension DateFormatter {
    static let localTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeZone = TimeZone(identifier: "America/Chicago")
        formatter.dateFormat = "h:mm a"
        return formatter
    }()
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
