import Foundation
import Sentry
import Testing
@testable import IlliniCover

@Suite("Fail-closed error monitoring")
@MainActor
struct ErrorMonitoringTests {
    @Test("The event scrubber preserves only crash correlation fields")
    func eventScrubber() throws {
        let event = Event(level: .error)
        event.releaseName = "com.illinicover.app.v2@2.0+abc"
        event.environment = "beta"
        event.message = SentryMessage(formatted: "venue=kams lat=40.11")
        event.error = NSError(domain: "secret@example.com", code: 1)
        event.logger = "private-route"
        event.serverName = "private-host"
        event.transaction = "/venues/private-id?lat=40.11"
        event.type = "transaction"
        event.tags = ["email": "secret@example.com"]
        event.extra = ["payload": ["latitude": 40.11]]
        event.context = ["report": ["longitude": -88.23]]
        event.request = SentryRequest()
        event.breadcrumbs = [Breadcrumb(level: .info, category: "report")]

        let frame = Frame()
        frame.fileName = "CoverReportView.swift"
        frame.function = "submit"
        frame.contextLine = "latitude: 40.11"
        frame.preContext = ["secret"]
        frame.postContext = ["secret"]
        frame.vars = ["email": "secret@example.com"]
        let stack = SentryStacktrace(frames: [frame], registers: ["x0": "secret"])
        let exception = Exception(value: "Report failed at 40.11,-88.23", type: "APIClientError")
        exception.module = "private-module"
        exception.stacktrace = stack
        event.exceptions = [exception]
        event.stacktrace = stack

        let clean = try #require(ErrorMonitoring.scrub(event))
        #expect(clean.releaseName == event.releaseName)
        #expect(clean.environment == "beta")
        #expect(clean.platform == "cocoa")
        #expect(clean.message == nil)
        #expect(clean.error == nil)
        #expect(clean.request == nil)
        #expect(clean.user == nil)
        #expect(clean.breadcrumbs == nil)
        #expect(clean.logger == nil)
        #expect(clean.serverName == nil)
        #expect(clean.transaction == nil)
        #expect(clean.type == nil)
        #expect(clean.tags == nil)
        #expect(clean.extra == nil)
        #expect(clean.context == nil)
        #expect(clean.modules == nil)
        #expect(clean.fingerprint == nil)
        #expect(clean.exceptions?.first?.type == "APIClientError")
        #expect(clean.exceptions?.first?.value == "redacted")
        #expect(clean.exceptions?.first?.mechanism == nil)
        #expect(clean.exceptions?.first?.module == nil)
        let cleanFrame = try #require(clean.stacktrace?.frames.first)
        #expect(cleanFrame.fileName == "CoverReportView.swift")
        #expect(cleanFrame.function == "submit")
        #expect(cleanFrame.contextLine == nil)
        #expect(cleanFrame.preContext == nil)
        #expect(cleanFrame.postContext == nil)
        #expect(cleanFrame.vars == nil)
        #expect(clean.stacktrace?.registers.isEmpty == true)
    }
}
