import Foundation

enum CoverSource: String, Codable, Hashable, Sendable {
    case live
    case advertised
    case historical
    case mixed
    case unconfirmed
    case unusual
    case unavailable

    var label: String {
        switch self {
        case .live: "Live"
        case .advertised: "Advertised cover"
        case .historical: "Historical estimate"
        case .mixed: "Mixed reports"
        case .unconfirmed, .unusual: "Unconfirmed"
        case .unavailable: "Unavailable"
        }
    }
}

enum CoverPrice: Codable, Equatable, Hashable, Sendable {
    case single(Int)
    case range(Int, Int)
    case unavailable

    private enum CodingKeys: String, CodingKey {
        case kind, amountCents, lowCents, highCents
    }

    private enum Kind: String, Codable {
        case single, range, unavailable, none
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let kind = try container.decode(Kind.self, forKey: .kind)
        switch kind {
        case .single:
            self = .single(try container.decode(Int.self, forKey: .amountCents))
        case .range:
            self = .range(
                try container.decode(Int.self, forKey: .lowCents),
                try container.decode(Int.self, forKey: .highCents)
            )
        case .none, .unavailable:
            self = .unavailable
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .single(let amount):
            try container.encode(Kind.single, forKey: .kind)
            try container.encode(amount, forKey: .amountCents)
        case .range(let low, let high):
            try container.encode(Kind.range, forKey: .kind)
            try container.encode(low, forKey: .lowCents)
            try container.encode(high, forKey: .highCents)
        case .unavailable:
            try container.encode(Kind.unavailable, forKey: .kind)
        }
    }

    var displayText: String {
        switch self {
        case .single(let cents): cents == 0 ? "$0" : Self.currency(cents)
        case .range(let low, let high): "\(Self.currency(low))–\(Self.currency(high))"
        case .unavailable: "—"
        }
    }

    var scalarCents: Int? {
        guard case .single(let cents) = self else { return nil }
        return cents
    }

    var spokenText: String {
        switch self {
        case .single(0): "No cover"
        case .single(let cents): "\(cents / 100) dollar cover"
        case .range(let low, let high): "Cover between \(low / 100) and \(high / 100) dollars"
        case .unavailable: "Cover unavailable"
        }
    }

    static func currency(_ cents: Int) -> String {
        let dollars = Double(cents) / 100
        if cents.isMultiple(of: 100) { return "$\(cents / 100)" }
        return dollars.formatted(.currency(code: "USD"))
    }

    /// The reporting domain accepts only $5 increments. Decisions retain
    /// their raw displayed amount for provenance; committing evidence uses
    /// this normalized value (positive halfway values round upward).
    static func normalizedReportCents(_ cents: Int) -> Int {
        let clamped = min(7_000, max(0, cents))
        return min(7_000, ((clamped + 250) / 500) * 500)
    }
}

struct Venue: Codable, Hashable, Identifiable, Sendable {
    let id: String
    let slug: String
    let name: String
    var address: String?
    var openedYear: Int?
}

struct VibeSummary: Codable, Equatable, Sendable {
    var lineLength: String?
    var lineSpeed: String?
    var crowdLevel: String?

    static let empty = VibeSummary()

    var tags: [String] {
        [
            lineLength.map { "\($0.capitalized) line" },
            lineSpeed.map { "\($0.capitalized) line speed" },
            crowdLevel.map(\.capitalized),
        ].compactMap { $0 }
    }
}

struct CoverDecision: Codable, Equatable, Hashable, Sendable {
    let price: CoverPrice
    let source: CoverSource
    let freshnessSeconds: Int?
    let decisionId: String?
    let status: String

    var isAdvertisedConflict: Bool { status.lowercased() == "advertised_conflict" }

    var presentationSourceLabel: String {
        isAdvertisedConflict ? "Advertised conflict" : source.label
    }

    var sourcePill: String {
        if isAdvertisedConflict { return "Advertised" }
        switch source {
        case .live: return (freshnessSeconds ?? .max) > 3_600 ? "Needs Update" : "Live Data"
        case .advertised: return "Advertised"
        case .historical: return "Historical"
        case .mixed: return "Live Data"
        case .unconfirmed, .unusual: return "Needs Update"
        case .unavailable: return "No Estimate"
        }
    }

    var evidenceText: String {
        if isAdvertisedConflict { return "Conflicting advertised prices" }
        switch source {
        case .live, .mixed:
            guard let freshnessSeconds else { return "Recent community reports" }
            if freshnessSeconds < 60 { return "Reported just now" }
            if freshnessSeconds < 3_600 { return "Reported \(freshnessSeconds / 60)m ago" }
            return "Reported \(freshnessSeconds / 3_600)h ago"
        case .advertised: return "Advertised by the venue"
        case .historical: return "Based on past reports around this time"
        case .unconfirmed, .unusual: return "A recent report looks unusual"
        case .unavailable: return "No useful reports yet"
        }
    }

    /// Returns presentation state whose age continues to advance after a
    /// response is cached. `freshnessSeconds` is the server's age at
    /// `serverGeneratedAt`; transport time and time spent in cache are added
    /// independently so clock skew cannot make a report appear newer.
    func displaying(
        at now: Date,
        serverGeneratedAt: Date,
        fetchedAt: Date
    ) -> CoverDecision {
        guard let freshnessSeconds else { return self }
        let transportAge = max(0, fetchedAt.timeIntervalSince(serverGeneratedAt))
        let cachedAge = max(0, now.timeIntervalSince(fetchedAt))
        let elapsed = min(Double(Int.max - freshnessSeconds), transportAge + cachedAge)
        return CoverDecision(
            price: price,
            source: source,
            freshnessSeconds: freshnessSeconds + Int(elapsed.rounded(.down)),
            decisionId: decisionId,
            status: status
        )
    }
}

struct CoverVenueCard: Codable, Identifiable, Sendable {
    let venue: Venue
    let cover: CoverDecision
    let recentReportCount: Int
    let latestActivityAt: Date?
    let vibes: VibeSummary

    var id: String { venue.id }

    private enum CodingKeys: String, CodingKey {
        case venue, cover, recentReportCount, latestActivityAt, vibes
    }

    init(
        venue: Venue,
        cover: CoverDecision,
        recentReportCount: Int,
        latestActivityAt: Date? = nil,
        vibes: VibeSummary
    ) {
        self.venue = venue
        self.cover = cover
        self.recentReportCount = recentReportCount
        self.latestActivityAt = latestActivityAt
        self.vibes = vibes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        venue = try c.decode(Venue.self, forKey: .venue)
        cover = try c.decodeIfPresent(CoverDecision.self, forKey: .cover) ?? CoverDecision(
            price: .unavailable,
            source: .unavailable,
            freshnessSeconds: nil,
            decisionId: nil,
            status: "unavailable"
        )
        recentReportCount = try c.decode(Int.self, forKey: .recentReportCount)
        latestActivityAt = try c.decodeIfPresent(Date.self, forKey: .latestActivityAt)
        vibes = try c.decodeIfPresent(VibeSummary.self, forKey: .vibes) ?? .empty
    }
}

struct CoverBoardResponse: Codable, Sendable {
    let serviceDate: String
    let generatedAt: Date
    let venues: [CoverVenueCard]
}

struct RecentCoverReport: Codable, Identifiable, Sendable {
    let id: String
    let price: CoverPrice?
    let observedAt: Date
    let sourceLabel: String?
    let locationContext: String?
    let vibes: [String]

    /// Public cover-history responses preserve compact evidence tokens such as
    /// `line_length:medium`. Keep those raw tokens for round-trip fidelity, but
    /// never expose wire spelling or underscores on the user-facing timeline.
    var displayVibes: [String] {
        vibes.map(Self.displayVibe)
    }

    static func displayVibe(_ raw: String) -> String {
        let parts = raw.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count == 2 else { return raw }
        let value = parts[1]
            .replacingOccurrences(of: "_", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return raw }
        switch parts[0] {
        case "line_length": return "\(value.capitalized) line"
        case "line_speed": return "\(value.capitalized) line speed"
        case "crowd_level": return value.capitalized
        default:
            let dimension = parts[0].replacingOccurrences(of: "_", with: " ").capitalized
            return "\(dimension): \(value.capitalized)"
        }
    }

    private enum CodingKeys: String, CodingKey {
        case id, submissionId, price, priceCents, observedAt, sourceLabel, interaction
        case locationContext, broadContext, vibes
    }

    init(id: String, price: CoverPrice?, observedAt: Date, sourceLabel: String?, locationContext: String?, vibes: [String]) {
        self.id = id
        self.price = price
        self.observedAt = observedAt
        self.sourceLabel = sourceLabel
        self.locationContext = locationContext
        self.vibes = vibes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? c.decode(String.self, forKey: .submissionId)
        if let explicit = try c.decodeIfPresent(CoverPrice.self, forKey: .price) {
            price = explicit
        } else if let cents = try c.decodeIfPresent(Int.self, forKey: .priceCents) {
            price = .single(cents)
        } else {
            price = nil
        }
        observedAt = try c.decode(Date.self, forKey: .observedAt)
        sourceLabel = try c.decodeIfPresent(String.self, forKey: .sourceLabel)
            ?? c.decodeIfPresent(String.self, forKey: .interaction)?.replacingOccurrences(of: "_", with: " ").capitalized
        locationContext = try c.decodeIfPresent(String.self, forKey: .locationContext)
            ?? c.decodeIfPresent(String.self, forKey: .broadContext)
        vibes = try c.decodeIfPresent([String].self, forKey: .vibes) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(price, forKey: .price)
        try c.encode(observedAt, forKey: .observedAt)
        try c.encodeIfPresent(sourceLabel, forKey: .sourceLabel)
        try c.encodeIfPresent(locationContext, forKey: .locationContext)
        try c.encode(vibes, forKey: .vibes)
    }
}

enum CoverHistoryAccessTier: String, Codable, Sendable {
    case limited
    case extended

    var title: String {
        switch self {
        case .limited: "Limited history"
        case .extended: "Extended history"
        }
    }
}

struct CoverHistoryResponse: Codable, Sendable {
    let venue: Venue
    let serviceDate: String
    let accessTier: CoverHistoryAccessTier
    let windowStart: Date
    let hasMore: Bool
    let reports: [RecentCoverReport]
}

struct VenueCoverResponse: Codable, Sendable {
    let venue: Venue
    let cover: CoverDecision
    let recentReports: [RecentCoverReport]
    let vibes: VibeSummary
    let deals: [Deal]

    private enum CodingKeys: String, CodingKey { case venue, cover, recentReports, vibes, deals }

    init(venue: Venue, cover: CoverDecision, recentReports: [RecentCoverReport], vibes: VibeSummary, deals: [Deal]) {
        self.venue = venue
        self.cover = cover
        self.recentReports = recentReports
        self.vibes = vibes
        self.deals = deals
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        venue = try c.decode(Venue.self, forKey: .venue)
        cover = try c.decodeIfPresent(CoverDecision.self, forKey: .cover) ?? CoverDecision(price: .unavailable, source: .unavailable, freshnessSeconds: nil, decisionId: nil, status: "unavailable")
        recentReports = try c.decodeIfPresent([RecentCoverReport].self, forKey: .recentReports) ?? []
        vibes = try c.decodeIfPresent(VibeSummary.self, forKey: .vibes) ?? .empty
        deals = try c.decodeIfPresent([Deal].self, forKey: .deals) ?? []
    }
}

enum VantagePoint: String, Codable, CaseIterable, Sendable {
    case outside
    case inside
    case unknown

    var label: String { rawValue.capitalized }
}

enum VibeDimension: String, Codable, CaseIterable, Sendable {
    case lineLength = "line_length"
    case lineSpeed = "line_speed"
    case crowdLevel = "crowd_level"
}

struct VibeObservationRequest: Codable, Equatable, Sendable {
    let dimension: VibeDimension
    let value: String
}

struct SubmissionLocation: Codable, Equatable, Sendable {
    let latitude: Double
    let longitude: Double
    let accuracyMeters: Double
    let permission: String

    init(latitude: Double, longitude: Double, accuracyMeters: Double, permission: String = "when_in_use") {
        self.latitude = latitude
        self.longitude = longitude
        self.accuracyMeters = accuracyMeters
        self.permission = permission
    }
}

enum CoverInteraction: String, Codable, Sendable {
    case confirm
    case correct
    case direct
    case quickConfirm = "quick_confirm"
    case manual
}

struct CoverObservationRequest: Codable, Equatable, Sendable {
    let priceCents: Int
    let interaction: CoverInteraction
    let displayedDecisionId: String?
    let pricePrefilled: Bool
    let priceTouched: Bool

    init(
        priceCents: Int,
        interaction: CoverInteraction,
        displayedDecisionId: String?,
        pricePrefilled: Bool,
        priceTouched: Bool
    ) {
        self.priceCents = priceCents
        self.interaction = interaction
        self.displayedDecisionId = displayedDecisionId
        self.pricePrefilled = pricePrefilled
        self.priceTouched = priceTouched
    }
}

struct CoverSubmissionRequest: Codable, Identifiable, Sendable {
    let submissionId: String
    let venueId: String
    let observedAt: Date
    let vantagePoint: VantagePoint
    let location: SubmissionLocation?
    let cover: CoverObservationRequest?
    let vibes: [VibeObservationRequest]
    let clientPlatform: String
    let clientVersion: String
    let entryPoint: String

    var id: String { submissionId }

    init(
        submissionId: String,
        venueId: String,
        observedAt: Date,
        vantagePoint: VantagePoint,
        location: SubmissionLocation?,
        cover: CoverObservationRequest?,
        vibes: [VibeObservationRequest],
        entryPoint: String = "report_sheet"
    ) {
        self.submissionId = submissionId
        self.venueId = venueId
        self.observedAt = observedAt
        self.vantagePoint = vantagePoint
        self.location = location
        self.cover = cover
        self.vibes = vibes
        clientPlatform = "ios"
        clientVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
        self.entryPoint = entryPoint
    }
}

struct SubmissionReceipt: Codable, Sendable {
    let submissionId: String
    let acceptedAt: Date?
    let requestId: String?
}

/// User-visible disposition of an evidence submission. A durable local save is
/// deliberately distinct from a server acknowledgement so quick actions never
/// claim that an offline report was received remotely.
enum SubmissionOutcome: Equatable, Sendable {
    case sent
    case queued
    case failed
}

enum DealCategory: String, Codable, CaseIterable, Sendable {
    case drink
    case food

    var label: String { rawValue.capitalized }
}

enum DealPrice: Codable, Equatable, Hashable, Sendable {
    case single(Int)
    case range(Int, Int)
    case percentOff(Int)
    case unknown

    private enum CodingKeys: String, CodingKey { case kind, amountCents, lowCents, highCents, percent }
    private enum Kind: String, Codable { case single, range, percentOff = "percent_off", unknown }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        switch try c.decode(Kind.self, forKey: .kind) {
        case .single: self = .single(try c.decode(Int.self, forKey: .amountCents))
        case .range: self = .range(try c.decode(Int.self, forKey: .lowCents), try c.decode(Int.self, forKey: .highCents))
        case .percentOff: self = .percentOff(try c.decode(Int.self, forKey: .percent))
        case .unknown: self = .unknown
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .single(let cents):
            try c.encode(Kind.single, forKey: .kind); try c.encode(cents, forKey: .amountCents)
        case .range(let low, let high):
            try c.encode(Kind.range, forKey: .kind); try c.encode(low, forKey: .lowCents); try c.encode(high, forKey: .highCents)
        case .percentOff(let percent):
            try c.encode(Kind.percentOff, forKey: .kind); try c.encode(percent, forKey: .percent)
        case .unknown: try c.encode(Kind.unknown, forKey: .kind)
        }
    }

    var displayText: String {
        switch self {
        case .single(let cents): CoverPrice.currency(cents)
        case .range(let low, let high): "\(CoverPrice.currency(low))–\(CoverPrice.currency(high))"
        case .percentOff(let percent): "\(percent)% off"
        case .unknown: "—"
        }
    }

    var identityComponent: String {
        switch self {
        case .single(let cents): "single:\(cents)"
        case .range(let low, let high): "range:\(low):\(high)"
        case .percentOff(let percent): "percent:\(percent)"
        case .unknown: "unknown"
        }
    }
}

enum DealTiming: Codable, Equatable, Hashable, Sendable {
    case allNight
    case untilSoldOut
    case unknown
    case before(String)
    case after(String)
    case between(String, String)

    private enum CodingKeys: String, CodingKey { case kind, startLocalTime, endLocalTime }
    private enum Kind: String, Codable { case allNight = "all_night", untilSoldOut = "until_sold_out", unknown, before, after, between }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        switch try c.decode(Kind.self, forKey: .kind) {
        case .allNight: self = .allNight
        case .untilSoldOut: self = .untilSoldOut
        case .unknown: self = .unknown
        case .before: self = .before(try c.decode(String.self, forKey: .endLocalTime))
        case .after: self = .after(try c.decode(String.self, forKey: .startLocalTime))
        case .between: self = .between(try c.decode(String.self, forKey: .startLocalTime), try c.decode(String.self, forKey: .endLocalTime))
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .allNight: try c.encode(Kind.allNight, forKey: .kind)
        case .untilSoldOut: try c.encode(Kind.untilSoldOut, forKey: .kind)
        case .unknown: try c.encode(Kind.unknown, forKey: .kind)
        case .before(let end): try c.encode(Kind.before, forKey: .kind); try c.encode(end, forKey: .endLocalTime)
        case .after(let start): try c.encode(Kind.after, forKey: .kind); try c.encode(start, forKey: .startLocalTime)
        case .between(let start, let end):
            try c.encode(Kind.between, forKey: .kind); try c.encode(start, forKey: .startLocalTime); try c.encode(end, forKey: .endLocalTime)
        }
    }

    var displayText: String? {
        switch self {
        case .allNight: "All night"
        case .untilSoldOut: "Until sold out"
        case .unknown: nil
        case .before(let time): "Before \(time)"
        case .after(let time): "After \(time)"
        case .between(let start, let end): "\(start)–\(end)"
        }
    }

    var identityComponent: String {
        switch self {
        case .allNight: "all_night"
        case .untilSoldOut: "until_sold_out"
        case .unknown: "unknown"
        case .before(let time): "before:\(time)"
        case .after(let time): "after:\(time)"
        case .between(let start, let end): "between:\(start):\(end)"
        }
    }

    static func flattened(
        description: String?,
        known: Bool,
        whileSuppliesLast: Bool
    ) -> DealTiming {
        if whileSuppliesLast { return .untilSoldOut }
        guard known, let raw = description?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else {
            return .unknown
        }
        if raw.localizedCaseInsensitiveCompare("All night") == .orderedSame { return .allNight }
        if raw.lowercased().hasPrefix("before ") {
            return .before(String(raw.dropFirst("before ".count)))
        }
        if raw.lowercased().hasPrefix("after ") {
            return .after(String(raw.dropFirst("after ".count)))
        }
        if raw.lowercased().hasPrefix("between "),
           let separator = raw.range(of: " and ", options: .caseInsensitive) {
            return .between(
                String(raw[raw.index(raw.startIndex, offsetBy: "between ".count)..<separator.lowerBound]),
                String(raw[separator.upperBound...])
            )
        }
        for separator in ["–", " — ", " - "] {
            if let range = raw.range(of: separator) {
                return .between(
                    String(raw[..<range.lowerBound]).trimmingCharacters(in: .whitespaces),
                    String(raw[range.upperBound...]).trimmingCharacters(in: .whitespaces)
                )
            }
        }
        return .unknown
    }
}

struct Deal: Codable, Identifiable, Hashable, Sendable {
    enum PresentationStatus: String, Sendable {
        case current
        case likely
        case advertised
        case unknown

        var label: String {
            switch self {
            case .current: "Current"
            case .likely: "Predicted"
            case .advertised: "Advertised"
            case .unknown: "Status unavailable"
            }
        }

        var isPrediction: Bool { self == .likely }
    }

    let id: String
    let familyId: String?
    let predictionId: String?
    let category: DealCategory
    let name: String
    let price: DealPrice
    /// The concrete quantity/size descriptor (for example, `16 oz`).
    /// Kept separate from `unit` because the API treats those as distinct
    /// offer-identity fields and corrections must round-trip them unchanged.
    let servingFormat: String?
    /// The container or sale unit (for example, `pint`, `can`, or `pitcher`).
    let unit: String?
    let timing: DealTiming
    let status: String
    let evidenceEventId: String?
    let latestActivityAt: Date?

    var presentationStatus: PresentationStatus {
        switch status.lowercased() {
        case "current": .current
        case "likely": .likely
        case "advertised": .advertised
        default: .unknown
        }
    }

    var serving: String? {
        Self.presentServing(format: servingFormat, unit: unit)
    }

    /// A delimiter-safe identity for a concrete offer variant. Suggestions do
    /// not have server deal UUIDs, so SwiftUI must key them by every field the
    /// server uses to distinguish variants rather than by family/name/price.
    var variantIdentity: String {
        let components = [
            familyId ?? "",
            category.rawValue,
            name,
            price.identityComponent,
            servingFormat ?? "",
            unit ?? "",
            timing.identityComponent,
        ]
        return components.map { "\($0.utf8.count)#\($0)" }.joined()
    }

    private enum CodingKeys: String, CodingKey {
        case id, familyId, canonicalFamilyId, predictionId, category, name, displayName, price, priceKind, priceCents
        case priceLowCents, priceHighCents, discountPercent, serving, servingFormat, unit, timing, timingDescription
        case timingKnown, whileSuppliesLast, status, evidenceEventId, latestEvidenceEventId, latestActivityAt
    }

    init(
        id: String,
        familyId: String?,
        predictionId: String? = nil,
        category: DealCategory,
        name: String,
        price: DealPrice,
        serving: String? = nil,
        servingFormat: String? = nil,
        unit: String? = nil,
        timing: DealTiming,
        status: String,
        evidenceEventId: String? = nil,
        latestActivityAt: Date? = nil
    ) {
        self.id = id
        self.familyId = familyId
        self.predictionId = predictionId
        self.category = category
        self.name = name
        self.price = price
        self.servingFormat = (servingFormat ?? serving)?.nilIfEmpty
        self.unit = unit?.nilIfEmpty
        self.timing = timing
        self.status = status
        self.evidenceEventId = evidenceEventId
        self.latestActivityAt = latestActivityAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        familyId = try c.decodeIfPresent(String.self, forKey: .familyId)
            ?? c.decodeIfPresent(String.self, forKey: .canonicalFamilyId)
        predictionId = try c.decodeIfPresent(String.self, forKey: .predictionId)
        category = DealCategory(rawValue: (try? c.decode(String.self, forKey: .category)) ?? "drink") ?? .drink
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? c.decode(String.self, forKey: .displayName)
        if let explicit = try c.decodeIfPresent(DealPrice.self, forKey: .price) {
            price = explicit
        } else if let low = try c.decodeIfPresent(Int.self, forKey: .priceLowCents),
                  let high = try c.decodeIfPresent(Int.self, forKey: .priceHighCents) {
            price = .range(low, high)
        } else if let cents = try c.decodeIfPresent(Int.self, forKey: .priceCents) {
            price = .single(cents)
        } else if let percent = try c.decodeIfPresent(Double.self, forKey: .discountPercent) {
            price = .percentOff(Int(percent.rounded()))
        } else {
            price = .unknown
        }
        servingFormat = (try c.decodeIfPresent(String.self, forKey: .servingFormat)
            ?? c.decodeIfPresent(String.self, forKey: .serving))?.nilIfEmpty
        unit = try c.decodeIfPresent(String.self, forKey: .unit)?.nilIfEmpty
        if let explicitTiming = try c.decodeIfPresent(DealTiming.self, forKey: .timing) {
            timing = explicitTiming
        } else {
            let known = try c.decodeIfPresent(Bool.self, forKey: .timingKnown) ?? false
            let soldOut = try c.decodeIfPresent(Bool.self, forKey: .whileSuppliesLast) ?? false
            let text = try c.decodeIfPresent(String.self, forKey: .timingDescription)
            timing = .flattened(description: text, known: known, whileSuppliesLast: soldOut)
        }
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "likely"
        evidenceEventId = try c.decodeIfPresent(String.self, forKey: .evidenceEventId)
            ?? c.decodeIfPresent(String.self, forKey: .latestEvidenceEventId)
        latestActivityAt = try c.decodeIfPresent(Date.self, forKey: .latestActivityAt)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(familyId, forKey: .familyId)
        try c.encodeIfPresent(predictionId, forKey: .predictionId)
        try c.encode(category, forKey: .category)
        try c.encode(name, forKey: .name)
        try c.encode(price, forKey: .price)
        try c.encodeIfPresent(servingFormat, forKey: .servingFormat)
        try c.encodeIfPresent(unit, forKey: .unit)
        try c.encode(timing, forKey: .timing)
        try c.encode(status, forKey: .status)
        try c.encodeIfPresent(evidenceEventId, forKey: .evidenceEventId)
        try c.encodeIfPresent(latestActivityAt, forKey: .latestActivityAt)
    }

    static func presentServing(format: String?, unit: String?) -> String? {
        let format = format?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        let unit = unit?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        if let format, let unit {
            if format.localizedCaseInsensitiveCompare(unit) == .orderedSame { return format }
            return "\(format) · \(unit.capitalized)"
        }
        return format ?? unit?.capitalized
    }
}

enum DealSuggestionMatchSource: String, Hashable, Sendable {
    case canonical
    case alias
    case historicalAlias = "historical_alias"
    case displayName = "display_name"
    case unit
}

struct DealSuggestion: Identifiable, Hashable, Sendable {
    let deal: Deal
    let sourceScope: String
    let lastSeenServiceDateLocal: String
    let matchedSource: DealSuggestionMatchSource?
    let matchedText: String?

    init(
        deal: Deal,
        sourceScope: String,
        lastSeenServiceDateLocal: String,
        matchedSource: DealSuggestionMatchSource? = nil,
        matchedText: String? = nil
    ) {
        self.deal = deal
        self.sourceScope = sourceScope
        self.lastSeenServiceDateLocal = lastSeenServiceDateLocal
        self.matchedSource = matchedSource
        self.matchedText = matchedText
    }

    var id: String { deal.variantIdentity }

    var provenanceText: String {
        provenanceText(referenceDate: .now)
    }

    func provenanceText(referenceDate: Date) -> String {
        let scope = sourceScope == "venue" ? "seen here" : "seen across bars"
        return "\(scope) · \(relativeLastSeen(referenceDate: referenceDate))"
    }

    var matchContextText: String? {
        if matchedSource == .historicalAlias {
            return "Matched a historical deal name"
        }
        guard matchedSource != nil, matchedSource != .canonical,
              let matchedText = matchedText?.trimmingCharacters(in: .whitespacesAndNewlines),
              !matchedText.isEmpty,
              matchedText.localizedCaseInsensitiveCompare(deal.name) != .orderedSame else { return nil }
        return "Matched “\(matchedText)”"
    }

    func relativeLastSeen(referenceDate: Date = .now) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Chicago")!
        let parts = lastSeenServiceDateLocal.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3,
              let date = calendar.date(from: DateComponents(
                timeZone: calendar.timeZone,
                year: parts[0], month: parts[1], day: parts[2], hour: 12
              )) else { return lastSeenServiceDateLocal }
        let today = calendar.startOfDay(for: referenceDate)
        let seen = calendar.startOfDay(for: date)
        let days = calendar.dateComponents([.day], from: seen, to: today).day ?? 0
        if days == 0 { return "today" }
        if days == 1 { return "yesterday" }
        if (2...7).contains(days) { return "\(days) days ago" }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }
}

struct VenueDeals: Codable, Identifiable, Sendable {
    let venue: Venue
    let deals: [Deal]
    var id: String { venue.id }
}

struct DealsResponse: Codable, Sendable {
    let serviceDate: String
    let generatedAt: Date
    let venues: [VenueDeals]
}

enum DealEvidenceAction: String, Codable, Sendable {
    case addMissing = "ADD_MISSING"
    case confirmPresent = "CONFIRM_PRESENT"
    case denyPresent = "DENY_PRESENT"
    case correct = "CORRECT"
}

extension SubmissionOutcome {
    var coverNotice: String {
        switch self {
        case .sent: "Report received."
        case .queued: "Saved offline. We’ll send it when you reconnect."
        case .failed: "Couldn’t submit. Try again."
        }
    }

    func dealNotice(for action: DealEvidenceAction) -> String {
        switch self {
        case .sent: action == .confirmPresent ? "Update submitted." : "Report received."
        case .queued: "Saved offline. We’ll send it when you reconnect."
        case .failed: "Couldn’t submit. Try again."
        }
    }
}

struct SubmittedDealShape: Codable, Sendable {
    let canonicalFamilyId: String?
    let category: DealCategory
    let name: String
    let price: DealPrice
    let servingFormat: String?
    let unit: String?
    let timing: DealTiming

    private enum CodingKeys: String, CodingKey {
        case canonicalFamilyId, category, name, displayName, price, priceKind, priceCents
        case priceLowCents, priceHighCents, discountPercent
        case serving, servingFormat, unit, timing, timingDescription, timingKnown, whileSuppliesLast
    }

    init(
        canonicalFamilyId: String? = nil,
        category: DealCategory,
        name: String,
        price: DealPrice,
        serving: String? = nil,
        servingFormat: String? = nil,
        unit: String? = nil,
        timing: DealTiming
    ) {
        self.canonicalFamilyId = canonicalFamilyId
        self.category = category
        self.name = name
        self.price = price
        // `serving` is retained as a source-compatible convenience for simple
        // presets. New code should pass both fields when editing an existing
        // concrete offer so a format/unit pair round-trips without flattening.
        self.servingFormat = (servingFormat ?? serving)?.nilIfEmpty
        self.unit = (unit ?? serving)?.nilIfEmpty
        self.timing = timing
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        canonicalFamilyId = try c.decodeIfPresent(String.self, forKey: .canonicalFamilyId)
        category = DealCategory(rawValue: try c.decode(String.self, forKey: .category)) ?? .drink
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? c.decode(String.self, forKey: .displayName)
        switch try c.decode(String.self, forKey: .priceKind) {
        case "absolute", "single":
            price = .single(try c.decode(Int.self, forKey: .priceCents))
        case "range":
            price = .range(
                try c.decode(Int.self, forKey: .priceLowCents),
                try c.decode(Int.self, forKey: .priceHighCents)
            )
        case "relative", "percent_off":
            price = .percentOff(Int(try c.decode(Double.self, forKey: .discountPercent).rounded()))
        default:
            price = .unknown
        }
        servingFormat = try c.decodeIfPresent(String.self, forKey: .servingFormat)
            ?? c.decodeIfPresent(String.self, forKey: .serving)
        unit = try c.decodeIfPresent(String.self, forKey: .unit)
        timing = .flattened(
            description: try c.decodeIfPresent(String.self, forKey: .timingDescription),
            known: try c.decodeIfPresent(Bool.self, forKey: .timingKnown) == true,
            whileSuppliesLast: try c.decodeIfPresent(Bool.self, forKey: .whileSuppliesLast) == true
        )
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(canonicalFamilyId, forKey: .canonicalFamilyId)
        try c.encode(category.rawValue, forKey: .category)
        try c.encode(name, forKey: .displayName)
        switch price {
        case .single(let cents):
            try c.encode("absolute", forKey: .priceKind); try c.encode(cents, forKey: .priceCents)
        case .range(let low, let high):
            try c.encode("range", forKey: .priceKind)
            try c.encode(low, forKey: .priceLowCents)
            try c.encode(high, forKey: .priceHighCents)
        case .percentOff(let percent):
            try c.encode("relative", forKey: .priceKind); try c.encode(percent, forKey: .discountPercent)
        case .unknown:
            try c.encode("unknown", forKey: .priceKind)
        }
        try c.encodeIfPresent(servingFormat, forKey: .servingFormat)
        try c.encodeIfPresent(unit, forKey: .unit)
        switch timing {
        case .allNight:
            try c.encode(true, forKey: .timingKnown); try c.encode("All night", forKey: .timingDescription)
        case .untilSoldOut:
            try c.encode(true, forKey: .timingKnown); try c.encode(true, forKey: .whileSuppliesLast)
        case .unknown:
            try c.encode(false, forKey: .timingKnown)
        case .before(let value):
            try c.encode(true, forKey: .timingKnown); try c.encode("Before \(value)", forKey: .timingDescription)
        case .after(let value):
            try c.encode(true, forKey: .timingKnown); try c.encode("After \(value)", forKey: .timingDescription)
        case .between(let start, let end):
            try c.encode(true, forKey: .timingKnown); try c.encode("\(start)–\(end)", forKey: .timingDescription)
        }
    }
}

struct DealEvidenceRequest: Codable, Identifiable, Sendable {
    let submissionId: String
    let venueId: String
    let observedAt: Date
    let action: DealEvidenceAction
    let targetDealId: String?
    let targetPredictionId: String?
    let supersedesEventId: String?
    let submittedDeal: SubmittedDealShape?
    let serviceDateLocal: String
    let targetLocalDateTime: Date?
    let clientPlatform: String
    let clientVersion: String
    let entryPoint: String
    let vantagePoint: VantagePoint
    let location: SubmissionLocation?
    var id: String { submissionId }

    private enum CodingKeys: String, CodingKey {
        case submissionId, venueId, observedAt, action, targetDealId, targetPredictionId
        case submittedDeal = "submittedDealShape", supersedesEventId
        case serviceDateLocal
        case targetLocalDateTime = "targetLocalDatetime"
        case clientPlatform, clientVersion, entryPoint, vantagePoint, location
    }

    init(
        submissionId: String,
        venueId: String,
        observedAt: Date,
        action: DealEvidenceAction,
        targetDealId: String?,
        targetPredictionId: String?,
        supersedesEventId: String? = nil,
        submittedDeal: SubmittedDealShape?,
        serviceDateLocal: String,
        targetLocalDateTime: Date?,
        entryPoint: String = "deal_composer",
        vantagePoint: VantagePoint = .unknown,
        location: SubmissionLocation? = nil
    ) {
        self.submissionId = submissionId
        self.venueId = venueId
        self.observedAt = observedAt
        self.action = action
        self.targetDealId = targetDealId
        self.targetPredictionId = targetPredictionId
        self.supersedesEventId = supersedesEventId
        self.submittedDeal = submittedDeal
        self.serviceDateLocal = serviceDateLocal
        self.targetLocalDateTime = targetLocalDateTime
        clientPlatform = "ios"
        clientVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
        self.entryPoint = entryPoint
        self.vantagePoint = vantagePoint
        self.location = location
    }
}

struct HandbookPageSummary: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let slug: String
    let title: String
    let summary: String
    let updatedAt: Date
}

struct HandbookPage: Codable, Identifiable, Sendable {
    let id: String
    let slug: String
    let title: String
    let summary: String
    let bodyMarkdown: String
    let updatedAt: Date
}

struct AccountSummary: Codable, Sendable {
    let id: String
    let email: String
    var firstName: String?
    var graduationYear: Int?
}

struct EntitlementSummary: Codable, Sendable {
    let premium: Bool
    let expiresAt: Date?

    private enum CodingKeys: String, CodingKey { case premium, expiresAt, entitlements }
    private struct Item: Codable { let identifier: String; let isActive: Bool; let expiresAt: Date? }

    init(premium: Bool, expiresAt: Date?) {
        self.premium = premium
        self.expiresAt = expiresAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let premium = try c.decodeIfPresent(Bool.self, forKey: .premium) {
            self.premium = premium
            expiresAt = try c.decodeIfPresent(Date.self, forKey: .expiresAt)
        } else {
            let items = try c.decodeIfPresent([Item].self, forKey: .entitlements) ?? []
            let premiumItem = items.first { $0.identifier == "premium" }
            premium = premiumItem?.isActive == true
            expiresAt = premiumItem?.expiresAt
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(premium, forKey: .premium)
        try c.encodeIfPresent(expiresAt, forKey: .expiresAt)
    }
}

struct AuthSessionResponse: Codable, Sendable {
    let account: AccountSummary
    let sessionToken: String
}

enum TimeMachineMode: String, Codable, Sendable {
    case past
    case current
    case future

    var title: String {
        switch self {
        case .past: "Retrospective reconstruction"
        case .current: "Current assessment"
        case .future: "Future prediction"
        }
    }
}

struct TimeMachineResponse: Codable, Sendable {
    let venue: Venue
    let targetTime: Date
    let knowledgeCutoff: Date
    let mode: TimeMachineMode
    let cover: CoverDecision

    private enum CodingKeys: String, CodingKey { case venue, targetTime, knowledgeCutoff, mode, cover }
    init(venue: Venue, targetTime: Date, knowledgeCutoff: Date, mode: TimeMachineMode, cover: CoverDecision) {
        self.venue = venue
        self.targetTime = targetTime
        self.knowledgeCutoff = knowledgeCutoff
        self.mode = mode
        self.cover = cover
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        venue = try c.decode(Venue.self, forKey: .venue)
        targetTime = try c.decode(Date.self, forKey: .targetTime)
        knowledgeCutoff = try c.decodeIfPresent(Date.self, forKey: .knowledgeCutoff) ?? targetTime
        mode = try c.decodeIfPresent(TimeMachineMode.self, forKey: .mode) ?? .current
        cover = try c.decodeIfPresent(CoverDecision.self, forKey: .cover) ?? CoverDecision(price: .unavailable, source: .unavailable, freshnessSeconds: nil, decisionId: nil, status: "unavailable")
    }
}

struct APIErrorPayload: Codable, Sendable {
    let code: String
    let message: String
    let requestId: String?
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
