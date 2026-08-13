import CoreLocation
import Testing
@testable import IlliniCover

@Suite("Submission location")
struct LocationClientTests {
    @Test("Core Location invalid negative accuracy never becomes report context") @MainActor
    func negativeAccuracyIsDiscarded() {
        let invalid = CLLocation(
            coordinate: .init(latitude: 40.109, longitude: -88.228),
            altitude: 0,
            horizontalAccuracy: -1,
            verticalAccuracy: -1,
            timestamp: .now
        )

        #expect(LocationClient.submissionLocation(from: invalid) == nil)
    }

    @Test("Valid accuracy and coordinates are preserved exactly") @MainActor
    func validAccuracyIsPreserved() throws {
        let valid = CLLocation(
            coordinate: .init(latitude: 40.109, longitude: -88.228),
            altitude: 0,
            horizontalAccuracy: 12.5,
            verticalAccuracy: -1,
            timestamp: .now
        )

        let submission = try #require(LocationClient.submissionLocation(from: valid))
        #expect(submission.latitude == 40.109)
        #expect(submission.longitude == -88.228)
        #expect(submission.accuracyMeters == 12.5)
    }
}
