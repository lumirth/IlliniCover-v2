import Foundation

struct Venue: Codable, Hashable, Identifiable, Sendable {
    let id: String
    let slug: String
    let name: String
    let address: String
    let openedYear: Int?
}

struct CoverPrice: Codable, Hashable, Sendable {
    let amountCents: Int?
    let highCents: Int?
    let kind: String
    let lowCents: Int?
    init(amountCents: Int? = nil, highCents: Int? = nil, kind: String, lowCents: Int? = nil) {
        self.amountCents = amountCents; self.highCents = highCents; self.kind = kind; self.lowCents = lowCents
    }
    var scalarCents: Int? { kind == "single" ? amountCents : nil }
    var floor: Int? { scalarCents ?? lowCents }
    var displayText: String {
        switch kind {
        case "single": amountCents.map(Self.money) ?? "—"
        case "range": lowCents.flatMap { low in highCents.map { "\(Self.money(low))–\(Self.money($0))" } } ?? "—"
        default: "—"
        }
    }
    var spokenText: String { displayText == "—" ? "cover unavailable" : "cover \(displayText)" }
    static func normalizedReportCents(_ cents: Int) -> Int { min(7_000, max(0, cents / 500 * 500)) }
    private static func money(_ cents: Int) -> String { cents % 100 == 0 ? "$\(cents / 100)" : String(format: "$%.2f", Double(cents) / 100) }
}

struct CoverDecision: Codable, Hashable, Sendable {
    let computedAt: Date
    let knowledgeCutoff: Date
    let price: CoverPrice
    let source: String
    let freshnessSeconds: Int?
    let status: String
    let targetTime: Date
    var presentationSourceLabel: String {
        switch status {
        case "unusual": "Unusual"
        case "live_mixed": "Mixed"
        case "reconstructed": "Historical"
        case "reconstructed_mixed": "Historical · Mixed"
        case "advertised_conflict": "Mixed · Advertised differs"
        case "unavailable": "Unavailable"
        default: source.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
    var evidenceText: String? { evidenceText(at: .now) }
    func evidenceText(at now: Date) -> String? {
        guard let freshnessSeconds else { return nil }
        let cacheAge = max(0, Int(now.timeIntervalSince(computedAt)))
        let minutes = max(0, freshnessSeconds + cacheAge) / 60
        let label = source == "live" ? "Reported" : (source == "advertised" ? "Published" : (source == "historical" ? "Historical evidence" : "Evidence"))
        if minutes == 0 { return "\(label) just now" }
        let age = minutes < 60 ? "\(minutes)m" : (minutes < 1_440 ? "\(minutes / 60)h" : "\(minutes / 1_440)d")
        return "\(label) \(age) ago"
    }
}

struct VibeSummary: Codable, Hashable, Sendable {
    let crowdLevel: String?
    let lineLength: String?
    let lineSpeed: String?
    var tags: [String] { [lineLength, lineSpeed, crowdLevel].compactMap { $0?.nilIfBlank } }
}

struct CoverVenueCard: Codable, Hashable, Identifiable, Sendable {
    let cover: CoverDecision?
    let latestActivityAt: Date?
    let recentReportCount: Int
    let venue: Venue
    let vibes: VibeSummary
    var id: String { venue.id }
}

struct CoverBoardResponse: Codable, Sendable { let generatedAt: Date; let serviceDate: String; let venues: [CoverVenueCard] }

struct RecentCoverReport: Codable, Identifiable, Sendable {
    let broadContext: String?
    let interaction: String
    let observedAt: Date
    let priceCents: Int?
    let receivedAt: Date
    let vibes: [String]
    var id: String { "\(observedAt.timeIntervalSince1970):\(priceCents ?? -1):\(interaction)" }
    var priceText: String { priceCents.map { CoverPrice(amountCents: $0, kind: "single").displayText } ?? "No cover price" }
}

enum CoverHistoryAccess: String, Codable, Sendable { case limited, extended; var title: String { self == .extended ? "Extended history" : "Recent history" } }
struct CoverHistoryResponse: Codable, Sendable {
    let accessTier: CoverHistoryAccess
    let hasMore: Bool
    let reports: [RecentCoverReport]
    let serviceDate: String
    let venue: Venue
    let windowStart: Date
}

struct VenueCoverResponse: Codable, Sendable {
    let cover: CoverDecision?
    let deals: [Deal]
    let recentReports: [RecentCoverReport]
    let venue: Venue
    let vibes: VibeSummary
}

struct Deal: Codable, Hashable, Identifiable, Sendable {
    let canonicalFamilyId: String
    let category: String
    let discountPercent: Double?
    let displayName: String
    let id: String
    let latestActivityAt: Date?
    let priceCents: Int?
    let priceHighCents: Int?
    let priceKind: String
    let priceLowCents: Int?
    let servingFormat: String
    let status: String
    let timingDescription: String?
    let timingKnown: Bool
    let unit: String
    let whileSuppliesLast: Bool
    var priceText: String { dealPriceText(priceKind, priceCents, priceLowCents, priceHighCents, discountPercent) }
    var timingText: String? {
        [timingKnown ? timingDescription?.nilIfBlank ?? "All night" : nil,
         whileSuppliesLast ? "While supplies last" : nil]
            .compactMap { $0 }.joined(separator: " · ").nilIfBlank
    }
    var servingText: String? { [servingFormat.nilIfBlank, unit.nilIfBlank].compactMap { $0 }.joined(separator: " · ").nilIfBlank }
}

struct DealSuggestion: Codable, Hashable, Identifiable, Sendable {
    let canonicalFamilyId: String
    let category: String
    let discountPercent: Double?
    let displayName: String
    let lastSeenServiceDateLocal: String
    let priceCents: Int?
    let priceHighCents: Int?
    let priceKind: String
    let priceLowCents: Int?
    let servingFormat: String
    let sourceScope: String
    let timingDescription: String?
    let timingKnown: Bool
    let unit: String
    let whileSuppliesLast: Bool
    var id: Self { self }
    var priceText: String { dealPriceText(priceKind, priceCents, priceLowCents, priceHighCents, discountPercent) }
    var provenanceText: String { "Last seen \(lastSeenServiceDateLocal) · \(sourceScope.replacingOccurrences(of: "_", with: " "))" }
}

private func dealPriceText(_ kind: String, _ single: Int?, _ low: Int?, _ high: Int?, _ percent: Double?) -> String {
    switch kind {
    case "absolute", "single": return single.map { CoverPrice(amountCents: $0, kind: "single").displayText } ?? "Price unknown"
    case "range": return low.flatMap { l in high.map { CoverPrice(highCents: $0, kind: "range", lowCents: l).displayText } } ?? "Price unknown"
    case "relative", "percent_off": return percent.map { "\(Int($0.rounded()))% off" } ?? "Discount"
    default: return "Price unknown"
    }
}

struct VenueDeals: Codable, Identifiable, Sendable { let deals: [Deal]; let venue: Venue; var id: String { venue.id } }
struct DealsResponse: Codable, Sendable { let generatedAt: Date; let serviceDate: String; let venues: [VenueDeals] }

enum CoverInteraction: String, Codable, Sendable { case confirm, correct, direct, quickConfirm = "quick_confirm", manual }
enum VantagePoint: String, Codable, CaseIterable, Sendable { case outside, inside, unknown }
enum VibeDimension: String, Codable, CaseIterable, Sendable { case lineLength = "line_length", lineSpeed = "line_speed", crowdLevel = "crowd_level" }
struct SubmissionLocation: Codable, Sendable { let accuracyMeters: Double; let latitude: Double; let longitude: Double; let permission: String? }
struct CoverInput: Codable, Sendable {
    let interaction: CoverInteraction
    let priceCents: Int
    let pricePrefilled: Bool
    let priceTouched: Bool
    let displayedSource: String?
    let displayedPriceKind: String?
    let displayedAmountCents: Int?
    let displayedLowCents: Int?
    let displayedHighCents: Int?
}
struct VibeInput: Codable, Sendable {
    let dimension: VibeDimension
    let value: String
    static let choices: [VibeDimension: [(label: String, value: String)]] = [
        .lineLength: [("Short", "short"), ("Medium", "medium"), ("Long", "long")],
        .lineSpeed: [("Slow", "slow"), ("Normal", "normal"), ("Fast", "fast")],
        .crowdLevel: [("Quiet", "quiet"), ("Busy", "busy"), ("Packed", "packed")],
    ]
}
struct CoverSubmissionRequest: Codable, Sendable {
    let clientPlatform: String
    let cover: CoverInput?
    let entryPoint: String
    let location: SubmissionLocation?
    let observedAt: Date
    let submissionId: String
    let vantagePoint: VantagePoint
    let venueId: String
    let vibes: [VibeInput]
}

enum DealEvidenceAction: String, Codable, Sendable { case addMissing = "ADD_MISSING", confirmPresent = "CONFIRM_PRESENT", denyPresent = "DENY_PRESENT", correct = "CORRECT" }
enum DealCategory: String, Codable, CaseIterable, Sendable { case drink, food }
struct DealShape: Codable, Sendable {
    let canonicalFamilyId: String?
    let category: DealCategory
    let discountPercent: Double?
    let displayName: String
    let priceCents: Int?
    let priceHighCents: Int?
    let priceKind: String
    let priceLowCents: Int?
    let servingFormat: String?
    let timingDescription: String?
    let timingKnown: Bool
    let unit: String?
    let whileSuppliesLast: Bool
}
struct DealEvidenceRequest: Codable, Sendable {
    let action: DealEvidenceAction
    let clientPlatform: String
    let entryPoint: String
    let location: SubmissionLocation?
    let observedAt: Date
    let serviceDateLocal: String
    let submissionId: String
    let submittedDealShape: DealShape?
    let targetDealId: String?
    let vantagePoint: VantagePoint
    let venueId: String
}

struct HandbookPageSummary: Codable, Hashable, Identifiable, Sendable { let id: String; let slug: String; let summary: String; let title: String; let updatedAt: Date }
struct HandbookPage: Codable, Identifiable, Sendable { let bodyMarkdown: String; let id: String; let slug: String; let summary: String; let title: String; let updatedAt: Date }
struct AccountSummary: Codable, Sendable { let displayName: String; let email: String; let id: String }
struct Entitlement: Codable, Sendable { let expiresAt: Date?; let identifier: String; let isActive: Bool }
struct EntitlementSummary: Codable, Sendable { let entitlements: [Entitlement]; var premium: Bool { entitlements.contains { $0.identifier == "premium" && $0.isActive } } }
enum TimeMachineMode: String, Codable, Sendable { case past, current, future; var title: String { rawValue.capitalized } }
struct TimeMachineResponse: Codable, Sendable { let cover: CoverDecision?; let knowledgeCutoff: Date; let mode: TimeMachineMode; let targetTime: Date; let venue: Venue }

enum SubmissionOutcome: Equatable, Sendable { case sent, queued, failed }
extension SubmissionOutcome {
    var coverNotice: String { self == .sent ? "Report sent" : (self == .queued ? "Saved to send when online" : "Report could not be saved") }
    func dealNotice(for action: DealEvidenceAction) -> String { self == .sent ? "Deal report sent" : (self == .queued ? "Saved to send when online" : "Report could not be saved") }
}
enum EmailCodeIntent: Sendable { case signIn, signUp }
struct EmailCodeChallenge: Sendable { let intent: EmailCodeIntent }
struct AuthSessionResponse: Sendable { let account: AccountSummary }

extension String {
    var nilIfBlank: String? { let value = trimmingCharacters(in: .whitespacesAndNewlines); return value.isEmpty ? nil : value }
}

enum ServiceNight {
    static var calendar: Calendar { var value = Calendar(identifier: .gregorian); value.timeZone = TimeZone(identifier: "America/Chicago")!; return value }
    static func serviceDate(containing date: Date) -> String {
        let localCalendar = calendar
        let serviceDay = localCalendar.component(.hour, from: date) < 5
            ? localCalendar.date(byAdding: .day, value: -1, to: localCalendar.startOfDay(for: date))!
            : date
        let parts = localCalendar.dateComponents([.year, .month, .day], from: serviceDay)
        return String(format: "%04d-%02d-%02d", parts.year!, parts.month!, parts.day!)
    }
}
