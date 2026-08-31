import Foundation
import Sentry

enum ErrorMonitoring {
    static func isEnabled(configuration: AppConfiguration) -> Bool {
        configuration.sentryDSN != nil
    }

    static func start(configuration: AppConfiguration) {
        guard let dsn = configuration.sentryDSN else { return }
        SentrySDK.start { options in
            options.dsn = dsn
            options.environment = configuration.deployment.rawValue
            options.releaseName = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String

            // Crash/error correlation only. Do not collect request URLs,
            // bodies, headers, breadcrumbs, screenshots, user identity, or
            // performance traces that could expose report/location context.
            options.sendDefaultPii = false
            options.tracesSampleRate = 0
            options.enableAutoPerformanceTracing = false
            options.enableNetworkTracking = false
            options.enableNetworkBreadcrumbs = false
            options.enableCaptureFailedRequests = false
            options.attachScreenshot = false
            options.attachViewHierarchy = false
            options.enableAppHangTracking = false
            options.enableAppHangTrackingV2 = false
            options.enableAutoSessionTracking = false
            options.maxBreadcrumbs = 0
            options.sessionReplay.sessionSampleRate = 0
            options.sessionReplay.onErrorSampleRate = 0
            options.beforeSend = scrub
        }
    }

    /// Builds a new event from a deliberately tiny allowlist. Rebuilding is
    /// safer than clearing known fields because future SDK fields cannot begin
    /// transmitting private report or location context by default.
    static func scrub(_ event: Event) -> Event? {
        let clean = Event(level: event.level)
        clean.eventId = event.eventId
        clean.timestamp = event.timestamp
        clean.platform = event.platform
        clean.releaseName = event.releaseName
        clean.environment = event.environment
        clean.debugMeta = event.debugMeta
        clean.stacktrace = scrub(event.stacktrace)
        clean.exceptions = event.exceptions?.map { exception in
            let cleanException = Exception(value: "redacted", type: exception.type)
            cleanException.threadId = exception.threadId
            cleanException.stacktrace = scrub(exception.stacktrace)
            return cleanException
        }
        clean.threads = event.threads?.map { thread in
            let cleanThread = SentryThread(threadId: thread.threadId)
            cleanThread.crashed = thread.crashed
            cleanThread.current = thread.current
            cleanThread.isMain = thread.isMain
            cleanThread.stacktrace = scrub(thread.stacktrace)
            return cleanThread
        }
        return clean
    }

    private static func scrub(_ stacktrace: SentryStacktrace?) -> SentryStacktrace? {
        guard let stacktrace else { return nil }
        let frames = stacktrace.frames.map { frame in
            let clean = Frame()
            clean.symbolAddress = frame.symbolAddress
            clean.fileName = frame.fileName
            clean.function = frame.function
            clean.module = frame.module
            clean.package = frame.package
            clean.imageAddress = frame.imageAddress
            clean.platform = frame.platform
            clean.instructionAddress = frame.instructionAddress
            clean.instruction = frame.instruction
            clean.lineNumber = frame.lineNumber
            clean.columnNumber = frame.columnNumber
            clean.inApp = frame.inApp
            clean.stackStart = frame.stackStart
            return clean
        }
        let clean = SentryStacktrace(frames: frames, registers: [:])
        clean.snapshot = stacktrace.snapshot
        return clean
    }
}
