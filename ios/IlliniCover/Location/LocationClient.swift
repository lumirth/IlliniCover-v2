import CoreLocation
import Observation

@MainActor
@Observable
final class LocationClient: NSObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var authorizationContinuation: CheckedContinuation<CLAuthorizationStatus, Never>?
    private var locationContinuation: CheckedContinuation<SubmissionLocation?, Never>?
    private var authorizationTimeout: Task<Void, Never>?
    private var locationTimeout: Task<Void, Never>?

    var authorizationStatus: CLAuthorizationStatus { manager.authorizationStatus }

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
    }

    func requestAuthorization() async -> CLAuthorizationStatus {
        let current = manager.authorizationStatus
        guard current == .notDetermined else { return current }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                authorizationContinuation?.resume(returning: manager.authorizationStatus)
                authorizationContinuation = continuation
                authorizationTimeout?.cancel()
                authorizationTimeout = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(8))
                    guard !Task.isCancelled else { return }
                    self?.finishAuthorization(with: self?.manager.authorizationStatus ?? .notDetermined)
                }
                manager.requestWhenInUseAuthorization()
            }
        } onCancel: {
            Task { @MainActor [weak self] in
                self?.finishAuthorization(with: self?.manager.authorizationStatus ?? .notDetermined)
            }
        }
    }

    func locationForSubmission() async -> SubmissionLocation? {
        let status = await requestAuthorization()
        guard status == .authorizedAlways || status == .authorizedWhenInUse else { return nil }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                finishLocation(with: nil)
                locationContinuation = continuation
                locationTimeout?.cancel()
                locationTimeout = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(8))
                    guard !Task.isCancelled else { return }
                    self?.finishLocation(with: nil)
                }
                manager.requestLocation()
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.finishLocation(with: nil) }
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard manager.authorizationStatus != .notDetermined else { return }
        finishAuthorization(with: manager.authorizationStatus)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let location = locations.last.flatMap(Self.submissionLocation)
        finishLocation(with: location)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finishLocation(with: nil)
    }

    private func finishAuthorization(with status: CLAuthorizationStatus) {
        authorizationTimeout?.cancel()
        authorizationTimeout = nil
        let continuation = authorizationContinuation
        authorizationContinuation = nil
        continuation?.resume(returning: status)
    }

    private func finishLocation(with location: SubmissionLocation?) {
        locationTimeout?.cancel()
        locationTimeout = nil
        let continuation = locationContinuation
        locationContinuation = nil
        continuation?.resume(returning: location)
    }

    static func submissionLocation(from location: CLLocation) -> SubmissionLocation? {
        guard location.horizontalAccuracy.isFinite,
              location.horizontalAccuracy >= 0,
              CLLocationCoordinate2DIsValid(location.coordinate)
        else { return nil }
        return SubmissionLocation(
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            accuracyMeters: location.horizontalAccuracy
        )
    }
}
