import Foundation
import Testing
@testable import IlliniCover

@Suite("Submission wire provenance")
struct WireProvenanceTests {
    @Test("Cover submission carries only the server decision receipt and interaction context")
    func coverProvenance() throws {
        let decision = CoverDecision(price: .range(1_000, 2_000), source: .mixed, freshnessSeconds: 120, decisionId: UUID().uuidString, status: "mixed")
        let cover = CoverObservationRequest(
            priceCents: 1_500,
            interaction: .correct,
            displayedDecisionId: decision.decisionId,
            pricePrefilled: false,
            priceTouched: true
        )
        let request = CoverSubmissionRequest(
            submissionId: UUID().uuidString,
            venueId: UUID().uuidString,
            observedAt: .now,
            vantagePoint: .outside,
            location: SubmissionLocation(latitude: 40, longitude: -88, accuracyMeters: 12),
            cover: cover,
            vibes: [.init(dimension: .lineLength, value: "long")],
            entryPoint: "test"
        )
        let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
        let encodedCover = try #require(object["cover"] as? [String: Any])
        #expect(encodedCover["displayedDecisionId"] as? String == decision.decisionId)
        #expect(encodedCover["displayedSource"] == nil)
        #expect(encodedCover["displayedPriceKind"] == nil)
        #expect(encodedCover["displayedPriceLowCents"] == nil)
        #expect(encodedCover["displayedPriceHighCents"] == nil)
        #expect(object["entryPoint"] as? String == "test")
    }

    @Test("Deal evidence uses server contract field names")
    func dealWireNames() throws {
        let request = DealEvidenceRequest(
            submissionId: UUID().uuidString,
            venueId: UUID().uuidString,
            observedAt: .now,
            action: .addMissing,
            targetDealId: nil,
            targetPredictionId: nil,
            submittedDeal: SubmittedDealShape(category: .drink, name: "Wells", price: .single(300), serving: "Glass", timing: .allNight),
            serviceDateLocal: "2026-08-12",
            targetLocalDateTime: nil
        )
        let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
        #expect(object["submittedDealShape"] != nil)
        #expect(object["targetLocalDatetime"] == nil)
    }
}
