import Foundation
import Testing
@testable import IlliniCover

@Suite("Chicago service night")
struct ServiceNightTests {
    @Test("Five AM cutoff uses Chicago wall time in both DST seasons")
    func cutoffAcrossDSTSeasons() throws {
        #expect(ServiceNight.serviceDate(containing: try date("2026-01-17T10:59:59Z")) == "2026-01-16")
        #expect(ServiceNight.serviceDate(containing: try date("2026-01-17T11:00:00Z")) == "2026-01-17")
        #expect(ServiceNight.serviceDate(containing: try date("2026-07-18T09:59:59Z")) == "2026-07-17")
        #expect(ServiceNight.serviceDate(containing: try date("2026-07-18T10:00:00Z")) == "2026-07-18")
    }

    @Test("Spring and fall clock transitions keep their local calendar date")
    func transitionNights() throws {
        #expect(ServiceNight.serviceDate(containing: try date("2026-03-08T09:30:00Z")) == "2026-03-07")
        #expect(ServiceNight.serviceDate(containing: try date("2026-11-01T09:30:00Z")) == "2026-10-31")
    }

    @Test("A cached deal slate becomes read-only exactly at the Chicago cutoff")
    @MainActor
    func dealSlateRollover() throws {
        let model = DealsModel()
        model.serviceDate = "2026-03-07"

        #expect(model.isCurrentServiceNight(at: try date("2026-03-08T09:59:59Z")))
        #expect(!model.isCurrentServiceNight(at: try date("2026-03-08T10:00:00Z")))

        model.serviceDate = "2026-10-31"
        #expect(model.isCurrentServiceNight(at: try date("2026-11-01T10:59:59Z")))
        #expect(!model.isCurrentServiceNight(at: try date("2026-11-01T11:00:00Z")))
    }

    private func date(_ value: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        return try #require(formatter.date(from: value))
    }
}
