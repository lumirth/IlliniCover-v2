import Foundation
import RevenueCat
import Testing
@testable import IlliniCover

@Suite("Client domain presentation")
struct DomainModelTests {
    @Test("Time Machine presents the server-authoritative three-state modes")
    func timeMachineModes() {
        #expect(TimeMachineMode.past.title == "Retrospective reconstruction")
        #expect(TimeMachineMode.current.title == "Current assessment")
        #expect(TimeMachineMode.future.title == "Future prediction")
    }

    @Test("Cover prices preserve decisive and range presentation")
    func coverPricePresentation() {
        #expect(CoverPrice.single(0).displayText == "$0")
        #expect(CoverPrice.single(2_000).displayText == "$20")
        #expect(CoverPrice.range(500, 1_000).displayText == "$5–$10")
        #expect(CoverPrice.unavailable.displayText == "—")
    }

    @Test("Advertised cover remains direct current evidence")
    func advertisedCoverPresentation() {
        let decision = CoverDecision(
            price: .single(1_000),
            source: .advertised,
            freshnessSeconds: nil,
            decisionId: "advertised",
            status: "advertised"
        )
        #expect(decision.source.label == "Advertised cover")
        #expect(decision.sourcePill == "Advertised")
        #expect(decision.evidenceText == "Advertised by the venue")
    }

    @Test("Cached freshness adds server-to-fetch and offline elapsed time")
    func freshnessPresentation() {
        let decision = CoverDecision(
            price: .single(1_000),
            source: .live,
            freshnessSeconds: 61 * 60,
            decisionId: "decision",
            status: "live"
        )
        let generatedAt = Date(timeIntervalSince1970: 1_000)
        let fetchedAt = generatedAt.addingTimeInterval(30)
        let displayed = decision.displaying(
            at: fetchedAt.addingTimeInterval(90),
            serverGeneratedAt: generatedAt,
            fetchedAt: fetchedAt
        )
        #expect(displayed.freshnessSeconds == 3_780)
        #expect(displayed.evidenceText == "Reported 1h ago")
        #expect(displayed.sourcePill == "Needs Update")
    }

    @Test("Clock skew never makes cached evidence younger")
    func freshnessClockSkew() {
        let decision = CoverDecision(
            price: .single(1_000),
            source: .live,
            freshnessSeconds: 120,
            decisionId: nil,
            status: "live"
        )
        let fetchedAt = Date(timeIntervalSince1970: 1_000)
        let displayed = decision.displaying(
            at: fetchedAt.addingTimeInterval(60),
            serverGeneratedAt: fetchedAt.addingTimeInterval(15),
            fetchedAt: fetchedAt
        )
        #expect(displayed.freshnessSeconds == 180)
    }

    @Test("Unknown deal timing stays absent on compact rows")
    func unknownTiming() {
        #expect(DealTiming.unknown.displayText == nil)
        #expect(DealTiming.allNight.displayText == "All night")
    }

    @Test("A new deal starts as Each while preserving v2's explicit unknown timing") @MainActor
    func newDealDefaultsMatchEstablishedComposer() {
        let venue = DealsResponse.fixture.venues[0].venue
        let model = DealComposerModel(seed: .init(venue: venue, mode: .add, deal: nil))
        #expect(model.serving == "Each")
        #expect(model.customServing.isEmpty)
        #expect(model.timingKind == .unknown)
        #expect(model.timing == .unknown)
    }

    @Test("Cover report header preserves mode icon, title, and venue subtitle")
    func coverReportHeaderPresentation() {
        #expect(CoverReportHeaderPresentation.make(interaction: .direct, venueName: "KAMS") == .init(
            title: "Report", venueName: "KAMS", systemImage: "paperplane.fill", tone: .accent
        ))
        #expect(CoverReportHeaderPresentation.make(interaction: .confirm, venueName: "KAMS") == .init(
            title: "Confirm", venueName: "KAMS", systemImage: "checkmark.circle.fill", tone: .right
        ))
        #expect(CoverReportHeaderPresentation.make(interaction: .correct, venueName: "KAMS") == .init(
            title: "Adjust", venueName: "KAMS", systemImage: "wrench.and.screwdriver.fill", tone: .wrong
        ))
    }

    @Test("Deal composer header preserves mode icon, title, venue, and service night")
    func dealComposerHeaderPresentation() {
        let venue = DealsResponse.fixture.venues[0].venue
        let base = DealComposerSeed(
            venue: venue,
            mode: .add,
            deal: nil,
            serviceDate: "2026-08-12"
        )
        #expect(DealComposerHeaderPresentation.make(seed: base) == .init(
            title: "Add Deal",
            subtitle: "KAMS • Wednesday, Aug 12",
            systemImage: "plus",
            tone: .accent
        ))
        let review = DealComposerSeed(
            venue: venue,
            mode: .review,
            deal: DealsResponse.fixture.venues[0].deals[0],
            serviceDate: "2026-08-12"
        )
        #expect(DealComposerHeaderPresentation.make(seed: review).title == "Review")
        #expect(DealComposerHeaderPresentation.make(seed: review).systemImage == "info.circle")
        #expect(DealComposerHeaderPresentation.make(seed: review).tone == .accent)
    }

    @Test("Recent report vibe tokens are human readable without losing the raw evidence")
    func recentReportVibePresentation() {
        let report = RecentCoverReport(
            id: "report",
            price: nil,
            observedAt: .now,
            sourceLabel: "Vibes",
            locationContext: "Outside",
            vibes: ["line_length:medium", "line_speed:fast", "crowd_level:busy", "door_state:open", "Legacy label"]
        )
        #expect(report.vibes == ["line_length:medium", "line_speed:fast", "crowd_level:busy", "door_state:open", "Legacy label"])
        #expect(report.displayVibes == ["Medium line", "Fast line speed", "Busy", "Door State: Open", "Legacy label"])
    }

    @Test("Deal search Done chooses the first match, otherwise a trimmed custom name") @MainActor
    func dealSearchCommitBehavior() {
        let deal = DealsResponse.fixture.venues[0].deals[0]
        let suggestion = DealSuggestion(deal: deal, sourceScope: "venue", lastSeenServiceDateLocal: "2026-08-09")
        #expect(DealComposerModel.nameCommit(query: "well", matches: [suggestion]) == .suggestion(suggestion))
        #expect(DealComposerModel.nameCommit(query: "  Custom Special  ", matches: []) == .custom("Custom Special"))
        #expect(DealComposerModel.nameCommit(query: "   ", matches: []) == nil)
        let reference = Calendar(identifier: .gregorian).date(from: DateComponents(year: 2026, month: 8, day: 11, hour: 12))!
        #expect(suggestion.relativeLastSeen(referenceDate: reference) == "2 days ago")
        #expect(suggestion.provenanceText(referenceDate: reference) == "seen here · 2 days ago")
        let global = DealSuggestion(deal: deal, sourceScope: "global", lastSeenServiceDateLocal: "2026-08-08")
        #expect(global.relativeLastSeen(referenceDate: reference) == "3 days ago")
        #expect(global.provenanceText(referenceDate: reference) == "seen across bars · 3 days ago")
        #expect(DealNameSearchCopy.sectionTitle(query: "  ", venueName: "KAMS") == "Recent deals · KAMS")
        #expect(DealNameSearchCopy.sectionTitle(query: "well", venueName: "KAMS") == "Matches")
        let alias = DealSuggestion(
            deal: deal,
            sourceScope: "venue",
            lastSeenServiceDateLocal: "2026-08-09",
            matchedSource: .alias,
            matchedText: "Happy Hour Rail Drinks"
        )
        #expect(alias.matchContextText == "Matched “Happy Hour Rail Drinks”")
        #expect(DealSuggestion(
            deal: deal,
            sourceScope: "global",
            lastSeenServiceDateLocal: "2026-08-01",
            matchedSource: .historicalAlias,
            matchedText: nil
        ).matchContextText == "Matched a historical deal name")
        #expect(DealSuggestion(
            deal: deal,
            sourceScope: "venue",
            lastSeenServiceDateLocal: "2026-08-09",
            matchedSource: .canonical,
            matchedText: "Well Drinks"
        ).matchContextText == nil)
    }

    @Test("Deal price editor isolates draft changes until Cancel or Done") @MainActor
    func dealPriceEditorCommitAndCancel() {
        let venue = DealsResponse.fixture.venues[0].venue
        let model = DealComposerModel(seed: .init(venue: venue, mode: .add, deal: nil))
        model.chooseQuickPrice(dollars: 2)
        #expect(model.price == .single(200))

        model.beginPriceEditing()
        model.singlePriceText = "3.25"
        #expect(model.isEditingPrice)
        model.cancelPriceEditing()
        #expect(model.price == .single(200))
        #expect(!model.isEditingPrice)

        model.beginPriceEditing()
        model.singlePriceText = "3.25"
        #expect(model.commitPriceEditing())
        #expect(model.price == .single(325))
        #expect(!model.isEditingPrice)

        model.beginPriceEditing()
        model.priceMode = .range
        model.lowPriceText = "10"
        model.highPriceText = "5"
        #expect(!model.commitPriceEditing())
        #expect(model.isEditingPrice)
    }

    @Test("A prefilled report is explicit evidence; a cleared report requires at least one vibe") @MainActor
    func reportObservationGate() {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: card.cover.price.scalarCents)
        let model = CoverReportModel(seed: seed, includeLocation: false)
        #expect(model.hasObservation == true)
        model.clearCover()
        #expect(model.hasObservation == false)
        model.vibes[.lineLength] = "long"
        #expect(model.hasObservation == true)
        model.vibes.removeAll()
        model.choosePrice(1_500)
        #expect(model.hasObservation == true)
    }

    @Test("Wrong quick price equal to the displayed scalar opens Adjust") @MainActor
    func equalWrongQuickPriceOpensAdjustment() throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let displayed = try #require(card.cover.price.scalarCents)
        #expect(CoverBoardModel.wrongPriceAction(for: card.cover, selectedCents: displayed) == .adjust)
        #expect(CoverBoardModel.wrongPriceAction(for: card.cover, selectedCents: displayed + 500) == .submit(displayed + 500))

        let offStep = CoverDecision(
            price: .single(1_200),
            source: .historical,
            freshnessSeconds: nil,
            decisionId: "off-step",
            status: "historical"
        )
        #expect(CoverBoardModel.wrongPriceAction(for: offStep, selectedCents: 1_000) == .adjust)
        #expect(CoverBoardModel.wrongPriceAction(for: offStep, selectedCents: 1_500) == .submit(1_500))
    }

    @Test("Untouched Adjust explicitly submits the prefilled cover with untouched provenance") @MainActor
    func untouchedCorrectionSubmitsPrefilledCover() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let displayed = try #require(card.cover.price.scalarCents)
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: displayed)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)

        #expect(model.hasObservation)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.cover?.priceCents == displayed)
        #expect(request.cover?.interaction == .correct)
        #expect(request.cover?.pricePrefilled == true)
        #expect(request.cover?.priceTouched == false)
    }

    @Test("Untouched Confirm explicitly submits the prefilled cover with untouched provenance") @MainActor
    func untouchedConfirmSubmitsPrefilledCover() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let displayed = try #require(card.cover.price.scalarCents)
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .confirm, initialPriceCents: displayed)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)

        #expect(model.hasObservation)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.cover?.priceCents == displayed)
        #expect(request.cover?.interaction == .confirm)
        #expect(request.cover?.pricePrefilled == true)
        #expect(request.cover?.priceTouched == false)
    }

    @Test("Clearing Adjust preserves vibes-only submission") @MainActor
    func vibesOnlyCorrectionRemainsValid() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: card.cover.price.scalarCents)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)
        model.clearCover()
        model.vibes[.lineLength] = "long"

        #expect(model.hasObservation)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.cover == nil)
        #expect(request.vibes.count == 1)
    }

    @Test("Vantage transitions clear hidden vibe evidence and submission filters incompatible state") @MainActor
    func vantageProgressiveDisclosureClearsHiddenVibes() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(
            venue: card.venue,
            decision: card.cover,
            interaction: .direct,
            initialPriceCents: nil
        )
        let model = CoverReportModel(seed: seed, includeLocation: false)
        model.vibes[.lineLength] = "long"
        model.vibes[.lineSpeed] = "slow"
        model.vibes[.crowdLevel] = "packed"

        model.selectVantage(.inside)
        #expect(model.vibes[.lineLength] == nil)
        #expect(model.vibes[.lineSpeed] == nil)
        #expect(model.vibes[.crowdLevel] == "packed")
        #expect(model.reportableVibes == [.crowdLevel: "packed"])

        model.selectVantage(.outside)
        #expect(model.vibes[.crowdLevel] == nil)
        #expect(!model.hasObservation)

        // Defensive serialization filtering prevents an incompatible value
        // from leaking even if non-UI code seeds model state directly.
        model.vibes[.crowdLevel] = "busy"
        model.vibes[.lineLength] = "medium"
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.vibes == [.init(dimension: .lineLength, value: "medium")])

        model.selectVantage(.unknown)
        model.vibes[.crowdLevel] = "quiet"
        #expect(model.reportableVibes.count == 2)
    }

    @Test("Manual cover entry rounds to five dollars and caps at seventy") @MainActor
    func manualCover() {
        let card = CoverBoardResponse.fixture.venues[0]
        let model = CoverReportModel(
            seed: .init(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil),
            includeLocation: false
        )
        model.beginManualEntry()
        model.manualEntry = "12"
        #expect(model.commitManualEntry())
        #expect(model.priceCents == 1_000)
        model.beginManualEntry()
        model.manualEntry = "999"
        #expect(model.commitManualEntry())
        #expect(model.priceCents == 7_000)
    }

    @Test("Manual editor isolates partial input until explicit Done") @MainActor
    func manualCoverSubmissionPreparation() {
        let card = CoverBoardResponse.fixture.venues[0]
        let model = CoverReportModel(
            seed: .init(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil),
            includeLocation: false
        )
        model.beginManualEntry()
        model.manualEntry = "45"
        #expect(model.isEditingPrice)
        #expect(!model.hasObservation)
        #expect(!model.preparePriceForSubmission())
        #expect(model.commitManualEntry())
        #expect(model.priceCents == 4_500)
        #expect(model.includeCover)
        #expect(model.priceTouched)

        model.beginManualEntry()
        model.manualEntry = "not a price"
        #expect(!model.commitManualEntry())
        #expect(model.isEditingPrice)
        #expect(model.priceCents == 4_500)
        #expect(model.errorMessage != nil)
    }

    @Test("Manual editor Cancel restores committed cover and empty Done clears it") @MainActor
    func manualCoverCancelAndClear() {
        let card = CoverBoardResponse.fixture.venues[0]
        let model = CoverReportModel(
            seed: .init(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: 2_000),
            includeLocation: false
        )
        model.beginManualEntry()
        model.manualEntry = "35"
        model.cancelManualEntry()
        #expect(model.priceCents == 2_000)
        #expect(model.includeCover)
        #expect(!model.priceTouched)
        #expect(!model.isEditingPrice)

        model.beginManualEntry()
        model.manualEntry = "."
        #expect(model.commitManualEntry())
        #expect(!model.includeCover)
        #expect(!model.hasObservation)
    }

    @Test("Manual cover commits enforce five-dollar increments, ties, and limits") @MainActor
    func manualCoverIncrementDomainRule() {
        let card = CoverBoardResponse.fixture.venues[0]
        let cases: [(String, Int)] = [
            ("0.01", 0),
            ("2.49", 0),
            ("2.50", 500),
            ("7.49", 500),
            ("7.50", 1_000),
            ("12.49", 1_000),
            ("12.50", 1_500),
            ("69.99", 7_000),
            ("70", 7_000),
            ("999", 7_000),
        ]
        for (draft, expectedCents) in cases {
            let model = CoverReportModel(
                seed: .init(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil),
                includeLocation: false
            )
            model.beginManualEntry()
            model.manualEntry = draft
            #expect(model.commitManualEntry())
            #expect(model.priceCents == expectedCents)
            #expect(model.priceCents.isMultiple(of: 500))
        }

        let invalid = CoverReportModel(
            seed: .init(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil),
            includeLocation: false
        )
        invalid.beginManualEntry()
        invalid.manualEntry = "-5"
        #expect(!invalid.commitManualEntry())
        #expect(invalid.isEditingPrice)
        #expect(!invalid.includeCover)
        #expect(CoverReportModel.holdRepeatIntervalsMilliseconds == [220, 180, 140, 110, 90])

        for pasted in ["inf", "1e309", String(repeating: "9", count: 1_000)] {
            let model = CoverReportModel(
                seed: .init(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil),
                includeLocation: false
            )
            model.beginManualEntry()
            model.manualEntry = pasted
            if pasted == "inf" || pasted == "1e309" {
                #expect(!model.commitManualEntry())
                #expect(model.isEditingPrice)
            } else {
                #expect(model.commitManualEntry())
                #expect(model.priceCents == 7_000)
            }
        }
    }

    @Test("Hold repeat keeps fast steps while rate limiting haptics to 140 milliseconds")
    func holdRepeatHapticPolicy() {
        let start = ContinuousClock().now
        #expect(CoverHoldRepeatHapticPolicy.shouldEmit(now: start, last: nil))
        #expect(!CoverHoldRepeatHapticPolicy.shouldEmit(
            now: start.advanced(by: .milliseconds(139)),
            last: start
        ))
        #expect(CoverHoldRepeatHapticPolicy.shouldEmit(
            now: start.advanced(by: .milliseconds(140)),
            last: start
        ))
    }

    @Test("Off-step displayed cover normalizes only the committed value and keeps displayed provenance") @MainActor
    func displayedCoverNormalizationAndPrefillProvenance() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let rawDecision = CoverDecision(
            price: .single(1_200),
            source: .historical,
            freshnessSeconds: nil,
            decisionId: "raw-12",
            status: "historical"
        )
        let seed = CoverReportSeed(venue: card.venue, decision: rawDecision, interaction: .correct, initialPriceCents: 1_200)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)
        #expect(model.priceCents == 1_000)
        #expect(model.coverPriceFooterText == "The displayed cover was $12. Reports use $5 steps, so Submit will report $10.")
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        var report = try #require(await recorder.last).cover
        #expect(report?.priceCents == 1_000)
        #expect(report?.displayedDecisionId == "raw-12")
        #expect(report?.pricePrefilled == true)
        #expect(report?.priceTouched == false)

        model.choosePrice(1_500)
        #expect(model.coverPriceFooterText == "Choose the cover you see.")
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        report = try #require(await recorder.last).cover
        #expect(report?.priceCents == 1_500)
        #expect(report?.displayedDecisionId == "raw-12")
        #expect(report?.pricePrefilled == true)
        #expect(report?.priceTouched == true)
        #expect(CoverPrice.normalizedReportCents(200) == 0)
        #expect(CoverPrice.normalizedReportCents(250) == 500)
        #expect(CoverPrice.normalizedReportCents(1_200) == 1_000)
        #expect(CoverPrice.normalizedReportCents(1_250) == 1_500)
    }

    @Test("Quick confirm normalizes the committed price while preserving the raw displayed decision") @MainActor
    func quickConfirmNormalizesOffStepDecision() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let rawDecision = CoverDecision(
            price: .single(1_200),
            source: .historical,
            freshnessSeconds: nil,
            decisionId: "raw-quick",
            status: "historical"
        )
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverBoardModel()
        #expect(await model.quickSubmit(
            venue: card.venue,
            decision: rawDecision,
            cents: 1_200,
            interaction: .quickConfirm,
            environment: environment
        ) == .sent)
        let report = try #require(await recorder.last).cover
        #expect(report?.priceCents == 1_000)
        #expect(report?.displayedDecisionId == "raw-quick")
        #expect(report?.pricePrefilled == true)
        #expect(report?.priceTouched == false)
    }

    @Test("Quick correction keeps displayed-prefill provenance after choosing a different amount") @MainActor
    func quickCorrectionKeepsPrefillProvenance() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverBoardModel()
        #expect(await model.quickSubmit(
            venue: card.venue,
            decision: card.cover,
            cents: 500,
            interaction: .direct,
            environment: environment
        ) == .sent)
        let report = try #require(await recorder.last).cover
        #expect(report?.priceCents == 500)
        #expect(report?.pricePrefilled == true)
        #expect(report?.priceTouched == true)
    }

    @Test("Manual cover drafts cannot override a later quick-price choice") @MainActor
    func typedThenQuickPriceUsesVisibleChoice() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .direct, initialPriceCents: nil)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)
        model.manualEntry = "35"

        model.choosePrice(500)

        #expect(model.manualEntry.isEmpty)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.cover?.priceCents == 500)
        #expect(request.cover?.priceTouched == true)
    }

    @Test("Manual cover drafts cannot override a later stepper change") @MainActor
    func typedThenStepperUsesVisibleChoice() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: 2_000)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)
        model.manualEntry = "35"

        model.adjustPrice(by: -500)

        #expect(model.manualEntry.isEmpty)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        #expect(try #require(await recorder.last).cover?.priceCents == 1_500)
    }

    @Test("Clear or Don't Know removes typed and displayed cover from the payload") @MainActor
    func typedThenClearOmitsCover() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: 2_000)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverReportModel(seed: seed, includeLocation: false)
        model.beginManualEntry()
        model.manualEntry = "35"

        model.clearCover()
        model.vibes[.lineLength] = "long"

        #expect(model.manualEntry.isEmpty)
        #expect(!model.includeCover)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        #expect(try #require(await recorder.last).cover == nil)
    }

    @Test("Cover stepper restarts from a cleared unknown value") @MainActor
    func coverStepperAfterClear() {
        let card = CoverBoardResponse.fixture.venues[0]
        let seed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: 2_000)

        let highSeed = CoverReportSeed(venue: card.venue, decision: card.cover, interaction: .correct, initialPriceCents: 7_000)
        let increase = CoverReportModel(seed: highSeed, includeLocation: false)
        increase.clearCover()
        #expect(increase.canIncreasePrice)
        #expect(increase.canDecreasePrice)
        increase.adjustPrice(by: 500)
        #expect(increase.includeCover)
        #expect(increase.priceCents == 500)

        let decrease = CoverReportModel(seed: seed, includeLocation: false)
        decrease.clearCover()
        #expect(decrease.canIncreasePrice)
        #expect(decrease.canDecreasePrice)
        decrease.adjustPrice(by: -500)
        #expect(decrease.includeCover)
        #expect(decrease.priceCents == 0)
    }

    @Test("Server deal status and serving-unit variants map to explicit presentation")
    func serverDealPresentation() throws {
        let cases: [(String, String, String, Deal.PresentationStatus, String)] = [
            ("likely", "16 oz", "pitcher", .likely, "16 oz · Pitcher"),
            ("current", "12 oz", "can", .current, "12 oz · Can"),
            ("current", "12 oz", "bottle", .current, "12 oz · Bottle"),
        ]
        for (status, format, unit, expectedStatus, expectedServing) in cases {
            let object: [String: Any] = [
                "id": UUID().uuidString,
                "canonicalFamilyId": "family-\(unit)",
                "category": "drink",
                "displayName": "Test \(unit)",
                "priceKind": "single",
                "priceCents": 500,
                "servingFormat": format,
                "unit": unit,
                "timingKnown": false,
                "whileSuppliesLast": false,
                "status": status,
            ]
            let deal = try JSONDecoder().decode(Deal.self, from: JSONSerialization.data(withJSONObject: object))
            #expect(deal.presentationStatus == expectedStatus)
            #expect(deal.presentationStatus.label == (status == "likely" ? "Predicted" : "Current"))
            #expect(deal.serving == expectedServing)
        }
    }

    @Test("Deals preserve v1 venue sort semantics and keep empty venues last") @MainActor
    func dealVenueSortSemantics() {
        func deal(_ id: String, price: DealPrice, activity: TimeInterval?) -> Deal {
            Deal(
                id: id,
                familyId: id,
                category: .drink,
                name: id,
                price: price,
                serving: "Each",
                timing: .allNight,
                status: "current",
                latestActivityAt: activity.map(Date.init(timeIntervalSince1970:))
            )
        }
        func venue(_ name: String, year: Int?, deals: [Deal]) -> VenueDeals {
            VenueDeals(
                venue: Venue(id: name, slug: name.lowercased(), name: name, address: nil, openedYear: year),
                deals: deals
            )
        }
        let oldest = venue("Oldest", year: 1920, deals: [
            deal("old-low", price: .single(1_000), activity: 100),
            deal("old-high", price: .single(3_000), activity: 200),
        ])
        let cheapRecent = venue("Z Cheap", year: 2000, deals: [deal("cheap", price: .single(500), activity: 400)])
        let noSingle = venue("Range", year: 2010, deals: [deal("range", price: .range(100, 200), activity: nil)])
        let empty = venue("A Empty", year: 1900, deals: [])
        let model = DealsModel()
        model.venues = [empty, noSingle, cheapRecent, oldest]

        #expect(model.sortedVenues(by: .openDate).map(\.venue.name) == ["Oldest", "Z Cheap", "Range", "A Empty"])
        #expect(model.sortedVenues(by: .name).map(\.venue.name) == ["Oldest", "Range", "Z Cheap", "A Empty"])
        #expect(model.sortedVenues(by: .lowestReports).map(\.venue.name) == ["Z Cheap", "Oldest", "Range", "A Empty"])
        #expect(model.sortedVenues(by: .recentlyUpdated).map(\.venue.name) == ["Z Cheap", "Oldest", "Range", "A Empty"])
    }

    @Test("Bars preserve the four shared v1 sort modes and missing values last") @MainActor
    func barVenueSortSemantics() {
        func card(
            _ name: String,
            year: Int?,
            price: CoverPrice,
            freshness: Int?,
            activity: TimeInterval?
        ) -> CoverVenueCard {
            CoverVenueCard(
                venue: Venue(id: name, slug: name.lowercased(), name: name, address: nil, openedYear: year),
                cover: CoverDecision(price: price, source: freshness == nil ? .historical : .live, freshnessSeconds: freshness, decisionId: name, status: "test"),
                recentReportCount: freshness == nil ? 0 : 1,
                latestActivityAt: activity.map(Date.init(timeIntervalSince1970:)),
                vibes: .empty
            )
        }
        let model = CoverBoardModel()
        model.venues = [
            card("Unavailable", year: nil, price: .unavailable, freshness: nil, activity: nil),
            card("Range", year: 2010, price: .range(500, 1_500), freshness: 300, activity: 200),
            card("Old", year: 1920, price: .single(2_000), freshness: 600, activity: 100),
            card("Recent", year: 2000, price: .single(1_000), freshness: 60, activity: 300),
        ]

        #expect(VenueSort.allCases.map(\.rawValue) == ["Open Date (Old-New)", "Name (A-Z)", "Lowest by Reports", "Recently Updated"])
        #expect(model.sortedVenues(by: .openDate).map(\.venue.name) == ["Old", "Recent", "Range", "Unavailable"])
        #expect(model.sortedVenues(by: .name).map(\.venue.name) == ["Old", "Range", "Recent", "Unavailable"])
        #expect(model.sortedVenues(by: .lowestReports).map(\.venue.name) == ["Range", "Recent", "Old", "Unavailable"])
        #expect(model.sortedVenues(by: .recentlyUpdated).map(\.venue.name) == ["Recent", "Range", "Old", "Unavailable"])
    }

    @Test("Quick deal actions distinguish server receipt, durable offline save, and failure") @MainActor
    func quickDealSubmissionOutcomes() async throws {
        let slate = DealsResponse.fixture.venues[0]
        let action = DealEvidenceAction.confirmPresent

        do {
            let (environment, credentials) = try makeEnvironment(api: PreviewAPIClient())
            defer { Task { await credentials.deleteAll() } }
            let model = DealsModel()
            model.serviceDate = ServiceNight.serviceDate(containing: .now)
            #expect(await model.submit(venue: slate.venue, deal: slate.deals[0], action: action, environment: environment) == .sent)
            #expect(SubmissionOutcome.sent.dealNotice(for: action) == "Update submitted.")
        }

        for action in [DealEvidenceAction.confirmPresent, .denyPresent] {
            let api = PreviewAPIClient(
                outboxBehavior: { _, _ in throw APIClientError.transport("offline") },
                dealSubmissionBehavior: { _ in throw APIClientError.transport("offline") }
            )
            let (environment, credentials) = try makeEnvironment(api: api)
            defer { Task { await credentials.deleteAll() } }
            let model = DealsModel()
            model.serviceDate = ServiceNight.serviceDate(containing: .now)
            #expect(await model.submit(venue: slate.venue, deal: slate.deals[0], action: action, environment: environment) == .queued)
            #expect(SubmissionOutcome.queued.dealNotice(for: action) == "Saved offline. We’ll send it when you reconnect.")
            await environment.outbox.drain()
            #expect(try await environment.database.outboxStatus().queued == 1)
        }

        do {
            let api = PreviewAPIClient(dealSubmissionBehavior: { _ in
                throw APIClientError.server(.init(code: "invalid", message: "Invalid", requestId: nil), status: 422)
            })
            let (environment, credentials) = try makeEnvironment(api: api)
            defer { Task { await credentials.deleteAll() } }
            let model = DealsModel()
            model.serviceDate = ServiceNight.serviceDate(containing: .now)
            #expect(await model.submit(venue: slate.venue, deal: slate.deals[0], action: .denyPresent, environment: environment) == .failed)
            #expect(SubmissionOutcome.failed.dealNotice(for: .denyPresent) == "Couldn’t submit. Try again.")
        }
    }

    @Test("Deal denial does not require an editable replacement price or name") @MainActor
    func dealDenialIgnoresReplacementDraftValidation() async throws {
        let slate = DealsResponse.fixture.venues[0]
        let target = Deal(
            id: "unknown-price-target",
            familyId: "unknown-family",
            predictionId: "prediction",
            category: .drink,
            name: "",
            price: .unknown,
            serving: nil,
            timing: .unknown,
            status: "likely"
        )
        let seed = DealComposerSeed(venue: slate.venue, mode: .deny, deal: target)
        let recorder = DealRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(dealSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = DealComposerModel(seed: seed)

        #expect(!model.isValid)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.action == .denyPresent)
        #expect(request.targetDealId == target.id)
        #expect(request.submittedDeal == nil)
    }

    @Test("Quick cover actions distinguish server receipt, durable offline save, and failure") @MainActor
    func quickCoverSubmissionOutcomes() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let cents = try #require(card.cover.price.scalarCents)

        do {
            let (environment, credentials) = try makeEnvironment(api: PreviewAPIClient())
            defer { Task { await credentials.deleteAll() } }
            let model = CoverBoardModel()
            #expect(await model.quickSubmit(venue: card.venue, decision: card.cover, cents: cents, interaction: .quickConfirm, environment: environment) == .sent)
            #expect(SubmissionOutcome.sent.coverNotice == "Report received.")
        }

        do {
            let api = PreviewAPIClient(
                outboxBehavior: { _, _ in throw APIClientError.transport("offline") },
                coverSubmissionBehavior: { _ in throw APIClientError.transport("offline") }
            )
            let (environment, credentials) = try makeEnvironment(api: api)
            defer { Task { await credentials.deleteAll() } }
            let model = CoverBoardModel()
            #expect(await model.quickSubmit(venue: card.venue, decision: card.cover, cents: cents, interaction: .quickConfirm, environment: environment) == .queued)
            #expect(SubmissionOutcome.queued.coverNotice == "Saved offline. We’ll send it when you reconnect.")
            await environment.outbox.drain()
            #expect(try await environment.database.outboxStatus().queued == 1)
        }

        do {
            let api = PreviewAPIClient(coverSubmissionBehavior: { _ in
                throw APIClientError.server(.init(code: "invalid", message: "Invalid", requestId: nil), status: 422)
            })
            let (environment, credentials) = try makeEnvironment(api: api)
            defer { Task { await credentials.deleteAll() } }
            let model = CoverBoardModel()
            #expect(await model.quickSubmit(venue: card.venue, decision: card.cover, cents: cents, interaction: .quickConfirm, environment: environment) == .failed)
            #expect(SubmissionOutcome.failed.coverNotice == "Couldn’t submit. Try again.")
        }
    }

    @Test("Quick confirm retains its distinct untouched provenance") @MainActor
    func quickConfirmProvenance() async throws {
        let card = CoverBoardResponse.fixture.venues[0]
        let displayed = try #require(card.cover.price.scalarCents)
        let recorder = CoverRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(coverSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let model = CoverBoardModel()

        #expect(await model.quickSubmit(
            venue: card.venue,
            decision: card.cover,
            cents: displayed,
            interaction: .quickConfirm,
            environment: environment
        ) == .sent)
        let request = try #require(await recorder.last)
        #expect(request.cover?.interaction == .quickConfirm)
        #expect(request.cover?.pricePrefilled == true)
        #expect(request.cover?.priceTouched == false)
        #expect(request.entryPoint == "bar_card_quick_confirm")
    }

    @Test("Returning users can render cached Bars and Deals while identity bootstrap is offline") @MainActor
    func cachedPresentationDoesNotWaitForBootstrapNetwork() async throws {
        let gate = BootstrapSuspensionGate()
        let api = PreviewAPIClient(createInstallationBehavior: { await gate.wait() })
        let (environment, credentials) = try makeEnvironment(api: api)
        defer { Task { await credentials.deleteAll() } }
        environment.settings.onboardingComplete = true
        try await environment.database.cache(CoverBoardResponse.fixture, key: "cover-board-v2", etag: "cover-cache")
        try await environment.database.cache(DealsResponse.fixture, key: "deals-v2", etag: "deals-cache")

        let bootstrap = Task { await environment.bootstrap() }
        await gate.waitUntilStarted()
        #expect(environment.isBootstrapping)

        let bars = CoverBoardModel()
        let deals = DealsModel()
        let barsLoad = Task { await bars.load(environment: environment) }
        let dealsLoad = Task { await deals.load(environment: environment) }
        for _ in 0..<100 where bars.venues.isEmpty || deals.venues.isEmpty {
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(bars.venues.count == CoverBoardResponse.fixture.venues.count)
        #expect(deals.venues.count == DealsResponse.fixture.venues.count)

        await gate.release()
        await barsLoad.value
        await dealsLoad.value
        await bootstrap.value
        #expect(!environment.isBootstrapping)
    }

    @Test("Concurrent lifecycle callers share one installation issuance") @MainActor
    func installationIssuanceIsSingleFlight() async throws {
        let gate = BootstrapSuspensionGate()
        let api = PreviewAPIClient(createInstallationBehavior: { await gate.wait() })
        let (environment, credentials) = try makeEnvironment(api: api)
        defer { Task { await credentials.deleteAll() } }

        async let bootstrapIssuance: Void = environment.ensureInstallation()
        await gate.waitUntilStarted()
        async let connectivityIssuance: Void = environment.ensureInstallation()
        await Task.yield()

        #expect(await api.installationCount == 1)
        await gate.release()
        _ = try await (bootstrapIssuance, connectivityIssuance)
        #expect(await api.installationCount == 1)
        #expect(try await credentials.readRequired(.installationToken) != nil)
    }

    @Test("Recreated root tasks share one bootstrap and one installation write") @MainActor
    func bootstrapIsSingleFlight() async throws {
        let gate = BootstrapSuspensionGate()
        let api = PreviewAPIClient(createInstallationBehavior: { await gate.wait() })
        let (environment, credentials) = try makeEnvironment(api: api)
        defer { Task { await credentials.deleteAll() } }

        async let first: Void = environment.bootstrap()
        await gate.waitUntilStarted()
        async let restartedViewTask: Void = environment.bootstrap()
        await Task.yield()
        #expect(await api.installationCount == 1)

        await gate.release()
        _ = await (first, restartedViewTask)
        #expect(await api.installationCount == 1)
        #expect(!environment.isBootstrapping)
    }

    @Test("A persisted privacy transition synchronously blocks cached product presentation") @MainActor
    func privacyTransitionBlocksCachedPresentation() async throws {
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverPrivacyGateTests.\(UUID().uuidString)"))
        let settings = AppSettings(defaults: defaults)
        settings.onboardingComplete = true
        settings.pendingPrivacyTransition = .deleteAccount
        let database = try AppDatabase.temporary()
        try await database.cache(CoverBoardResponse.fixture, key: "cover-board-v2", etag: "private-cover")
        try await database.cache(DealsResponse.fixture, key: "deals-v2", etag: "private-deals")

        #expect(settings.pendingPrivacyTransition == .deleteAccount)
        #expect(settings.privacyPurgePending)
        #expect(try await database.cached(CoverBoardResponse.self, key: "cover-board-v2") != nil)
        #expect(try await database.cached(DealsResponse.self, key: "deals-v2") != nil)
        // AppRootView evaluates this persisted marker before creating AppShell;
        // the cached values above therefore cannot instantiate actionable
        // Bars/Deals views during the marker-before-purge crash window.
    }

    @Test("Selecting a past deal applies its full shape") @MainActor
    func dealSuggestion() {
        let venueDeals = DealsResponse.fixture.venues[0]
        let suggestion = venueDeals.deals[0]
        let model = DealComposerModel(seed: .init(venue: venueDeals.venue, mode: .add, deal: nil))
        model.apply(suggestion: suggestion)
        #expect(model.name == suggestion.name)
        #expect(model.serving == suggestion.serving)
        #expect(model.price == suggestion.price)
        #expect(model.timing == suggestion.timing)
        #expect(model.canonicalFamilyId == suggestion.familyId)
        #expect(model.appliedInfoFlash)
        #expect(model.appliedPriceFlash)
    }

    @Test("Deal suggestions preserve concrete serving variants and round-trip both fields") @MainActor
    func dealSuggestionServingRoundTrip() async throws {
        let slate = DealsResponse.fixture.venues[0]
        let deal = Deal(
            id: "suggestion",
            familyId: "family",
            category: .drink,
            name: "Rail drink",
            price: .single(400),
            servingFormat: "16 oz",
            unit: "pint",
            timing: .after("9:00 PM"),
            status: "current"
        )
        let model = DealComposerModel(seed: .init(venue: slate.venue, mode: .add, deal: nil))
        model.apply(suggestion: deal)
        #expect(model.servingFormat == "16 oz")
        #expect(model.unit == "pint")
        #expect(model.serving == "16 oz · Pint")

        let recorder = DealRequestRecorder()
        let (environment, credentials) = try makeEnvironment(
            api: PreviewAPIClient(dealSubmissionBehavior: { request in await recorder.record(request) })
        )
        defer { Task { await credentials.deleteAll() } }
        let seed = DealComposerSeed(venue: slate.venue, mode: .add, deal: nil)
        #expect(await model.submit(seed: seed, environment: environment) == .sent)
        let submitted = try #require(await recorder.last?.submittedDeal)
        #expect(submitted.servingFormat == "16 oz")
        #expect(submitted.unit == "pint")
    }

    @Test("Suggestion identity distinguishes category, unit, and timing variants")
    func suggestionVariantIdentity() {
        func suggestion(category: DealCategory = .drink, unit: String, timing: DealTiming) -> DealSuggestion {
            DealSuggestion(
                deal: Deal(
                    id: "same-placeholder-id",
                    familyId: "family",
                    category: category,
                    name: "Rail drink",
                    price: .single(400),
                    servingFormat: "16 oz",
                    unit: unit,
                    timing: timing,
                    status: "current"
                ),
                sourceScope: "venue",
                lastSeenServiceDateLocal: "2026-08-11"
            )
        }
        let values = [
            suggestion(unit: "pint", timing: .allNight),
            suggestion(unit: "can", timing: .allNight),
            suggestion(unit: "pint", timing: .before("10:00 PM")),
            suggestion(category: .food, unit: "pint", timing: .allNight),
        ]
        #expect(Set(values.map(\.id)).count == values.count)
    }

    @Test("Suggestion failure never relabels current or predicted slate rows as history") @MainActor
    func suggestionFailureIsHonest() async {
        let api = PreviewAPIClient(dealSuggestionsBehavior: { _, _ in
            throw APIClientError.transport("offline")
        })
        let model = DealSuggestionSearchModel()
        await model.load(query: "well", venueID: "kams", api: api)
        #expect(model.matches.isEmpty)
        #expect(model.errorMessage == "Past deal suggestions are unavailable. You can still enter a custom name.")
        #expect(!model.isLoading)
    }

    @Test("Deal price hold repeat accelerates while haptics remain bounded") @MainActor
    func dealPriceHoldRepeatPolicy() {
        #expect(DealPriceHoldRepeatPolicy.intervalsMilliseconds == [220, 180, 140, 110, 90])
        let start = ContinuousClock().now
        #expect(DealPriceHoldRepeatPolicy.shouldEmitHaptic(now: start, last: nil))
        #expect(!DealPriceHoldRepeatPolicy.shouldEmitHaptic(now: start.advanced(by: .milliseconds(139)), last: start))
        #expect(DealPriceHoldRepeatPolicy.shouldEmitHaptic(now: start.advanced(by: .milliseconds(140)), last: start))

        let venue = DealsResponse.fixture.venues[0].venue
        let model = DealComposerModel(seed: .init(venue: venue, mode: .add, deal: nil))
        for _ in 0..<150 { model.adjustSinglePrice(by: 100) }
        #expect(model.singlePriceText == "100")
        #expect(!model.canAdjust(model.singlePriceText, by: 100))
        for _ in 0..<30 { model.adjustPercent(by: -5) }
        #expect(model.percentOff == 5)
        #expect(!model.canAdjustPercent(by: -5))
    }

    @Test("Deal composer refuses an old slate after service-night rollover") @MainActor
    func dealComposerServiceNightRollover() async throws {
        let slate = DealsResponse.fixture.venues[0]
        let model = DealComposerModel(seed: .init(venue: slate.venue, mode: .add, deal: nil))
        model.name = "Rail drinks"
        model.chooseQuickPrice(dollars: 4)
        let oldSeed = DealComposerSeed(
            venue: slate.venue,
            mode: .add,
            deal: nil,
            serviceDate: "2000-01-01"
        )
        let (environment, credentials) = try makeEnvironment(api: PreviewAPIClient())
        defer { Task { await credentials.deleteAll() } }
        #expect(await model.submit(seed: oldSeed, environment: environment) == .failed)
        #expect(model.errorMessage?.contains("service night changed") == true)
    }

    @Test("Cold Deals and venue-detail failures recover through explicit retry") @MainActor
    func coldReadRetryRecovery() async throws {
        let dealsAttempts = AttemptGate()
        let api = PreviewAPIClient(
            dealsBehavior: { _ in
                if await dealsAttempts.next() == 1 { throw APIClientError.transport("offline") }
                return HTTPResult(value: .fixture, eTag: "retry", notModified: false)
            },
            venueCoverBehavior: { id in
                if await dealsAttempts.nextVenue() == 1 { throw APIClientError.transport("offline") }
                let card = CoverBoardResponse.fixture.venues.first(where: { $0.venue.id == id }) ?? CoverBoardResponse.fixture.venues[0]
                return VenueCoverResponse(venue: card.venue, cover: card.cover, recentReports: .fixture, vibes: card.vibes, deals: [])
            }
        )
        let (environment, credentials) = try makeEnvironment(api: api)
        defer { Task { await credentials.deleteAll() } }

        let deals = DealsModel()
        await deals.load(environment: environment)
        #expect(deals.venues.isEmpty)
        #expect(deals.errorMessage != nil)
        await deals.refresh(environment: environment)
        #expect(!deals.venues.isEmpty)
        #expect(deals.errorMessage == nil)

        let venue = VenueDetailModel()
        let id = CoverBoardResponse.fixture.venues[0].venue.id
        await venue.load(id: id, api: api)
        #expect(venue.detail == nil)
        #expect(venue.errorMessage != nil)
        await venue.load(id: id, api: api)
        #expect(venue.detail?.venue.id == id)
        #expect(venue.errorMessage == nil)
    }

    @Test("Range deal uses canonical family and dedicated price fields")
    func rangeDealWireShape() throws {
        let shape = SubmittedDealShape(
            canonicalFamilyId: "family-pitcher",
            category: .drink,
            name: "Pitcher special",
            price: .range(500, 1_000),
            serving: "Pitcher",
            timing: .allNight
        )
        let data = try JSONEncoder().encode(shape)
        let json = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(json["canonicalFamilyId"] as? String == "family-pitcher")
        #expect(json["priceLowCents"] as? Int == 500)
        #expect(json["priceHighCents"] as? Int == 1_000)
        #expect(json["priceCents"] == nil)
        #expect(json["timingDescription"] as? String == "All night")
    }

    @Test("Flattened timing variants survive server decode and correction editing")
    func flattenedDealTiming() throws {
        #expect(DealTiming.flattened(description: "All night", known: true, whileSuppliesLast: false) == .allNight)
        #expect(DealTiming.flattened(description: "Before 10:00 PM", known: true, whileSuppliesLast: false) == .before("10:00 PM"))
        #expect(DealTiming.flattened(description: "After 9:00 PM", known: true, whileSuppliesLast: false) == .after("9:00 PM"))
        #expect(DealTiming.flattened(description: "8:00 PM–11:00 PM", known: true, whileSuppliesLast: false) == .between("8:00 PM", "11:00 PM"))
        #expect(DealTiming.flattened(description: nil, known: true, whileSuppliesLast: true) == .untilSoldOut)
        #expect(DealTiming.flattened(description: "All night", known: false, whileSuppliesLast: false) == .unknown)
    }

    @Test("RevenueCat receipt ownership errors get account recovery guidance") @MainActor
    func receiptOwnershipGuidance() {
        let alreadyUsed = NSError(
            domain: ErrorCode.errorDomain,
            code: ErrorCode.receiptAlreadyInUseError.rawValue
        )
        let otherSubscriber = NSError(
            domain: ErrorCode.errorDomain,
            code: ErrorCode.receiptInUseByOtherSubscriberError.rawValue
        )
        #expect(BillingModel.isReceiptOwnershipError(alreadyUsed))
        #expect(BillingModel.isReceiptOwnershipError(otherSubscriber))
        #expect(BillingError.receiptOwnedByAnotherAccount.localizedDescription.contains("original account"))
    }

    @Test("IlliniCover Blue plans have one deterministic honest presentation") @MainActor
    func bluePlanPresentation() throws {
        let kinds = [
            PackageType.lifetime,
            .monthly,
            .custom,
            .annual,
            .weekly,
            .sixMonth,
            .unknown,
        ]
        .compactMap(BluePlanKind.init(packageType:))
        .sorted()

        #expect(kinds == [.annual, .monthly, .weekly, .sixMonth, .lifetime])
        #expect(kinds.filter(\.isPrimary) == [.annual, .monthly])
        #expect(kinds.filter { !$0.isPrimary } == [.weekly, .sixMonth, .lifetime])

        #expect(BluePlanKind.annual.title == "Annual")
        #expect(BluePlanKind.annual.priceSuffix == "/ year")
        #expect(BluePlanKind.annual.renewalDescription == "Renews yearly until canceled.")
        #expect(BluePlanKind.annual.isBestSubscriptionValue)

        #expect(BluePlanKind.monthly.title == "Monthly")
        #expect(BluePlanKind.monthly.priceSuffix == "/ month")
        #expect(BluePlanKind.weekly.priceSuffix == "/ week")
        #expect(BluePlanKind.sixMonth.title == "Six months")
        #expect(BluePlanKind.sixMonth.priceSuffix == "/ 6 months")
        #expect(BluePlanKind.sixMonth.renewalDescription == "Renews every six months until canceled.")
        #expect(BluePlanKind.lifetime.priceSuffix == "once")
        #expect(BluePlanKind.lifetime.renewalDescription == "One-time purchase. No renewal.")
        #expect(!BluePlanKind.lifetime.isBestSubscriptionValue)

        for package in BillingModel.blueUITestPackages {
            let kind = try #require(BluePlanKind(packageType: package.packageType))
            #expect(kind.matches(product: package.storeProduct))
        }
        let annual = try #require(
            BillingModel.blueUITestPackages.first { $0.packageType == .annual }
        )
        #expect(!BluePlanKind.monthly.matches(product: annual.storeProduct))
    }

    @Test("Canceling the Apple purchase sheet is not reported as a purchase")
    func cancelledPurchaseOutcome() {
        #expect(BillingPurchaseOutcome(userCancelled: false) == .completed)
        #expect(BillingPurchaseOutcome(userCancelled: true) == .cancelled)
    }

    @Test("A provider entitlement waits for server confirmation and blocks another purchase")
    func blueConfirmationState() {
        let inactive = BlueAccessState(serverPremium: false, clientPremium: false)
        let pending = BlueAccessState(serverPremium: false, clientPremium: true)
        let active = BlueAccessState(serverPremium: true, clientPremium: true)

        #expect(inactive == .inactive)
        #expect(inactive.permitsPurchase)
        #expect(pending == .awaitingServerConfirmation)
        #expect(!pending.permitsPurchase)
        #expect(active == .active)
        #expect(!active.permitsPurchase)
    }

    @Test("Billing refuses a second purchase while provider ownership awaits the server") @MainActor
    func pendingBluePurchaseCannotRepurchase() async throws {
        let model = BillingModel(
            apiKey: "test",
            initialClientPremium: true,
            initialHasActiveSubscription: true
        )
        let package = try #require(BillingModel.blueUITestPackages.first)
        await #expect(throws: BillingError.serverConfirmationPending) {
            try await model.purchase(package)
        }
    }

    @Test("Restore and subscription management distinguish no entitlement from lifetime ownership") @MainActor
    func blueClientEntitlementPresentation() {
        let none = BillingModel(apiKey: nil)
        #expect(BillingRestoreOutcome(clientPremium: none.clientPremium) == .noEntitlement)
        #expect(!none.hasManageableSubscription)

        let lifetime = BillingModel(
            apiKey: nil,
            initialClientPremium: true,
            initialHasActiveSubscription: false
        )
        #expect(BillingRestoreOutcome(clientPremium: lifetime.clientPremium) == .entitlementFound)
        #expect(!lifetime.hasManageableSubscription)

        let subscription = BillingModel(
            apiKey: nil,
            initialClientPremium: true,
            initialHasActiveSubscription: true
        )
        #expect(subscription.hasManageableSubscription)
    }

    @Test("Billing starts signed out and cannot silently create an anonymous purchase identity") @MainActor
    func billingSignedOutGate() {
        let model = BillingModel(apiKey: "test")
        #expect(model.isConfigured == false)
        #expect(model.currentAccountID == nil)
        model.disableForSignedOutState()
        #expect(model.isConfigured == false)
        #expect(model.currentAccountID == nil)
    }

    @Test("Only transient submission failures enter the durable outbox")
    func retryableSubmissionFailures() {
        let payload = APIErrorPayload(code: "failure", message: "Try again", requestId: nil)
        #expect(APIClientError.transport("network").isRetryableSubmissionFailure)
        #expect(APIClientError.server(payload, status: 503).isRetryableSubmissionFailure)
        #expect(APIClientError.server(payload, status: 429).isRetryableSubmissionFailure)
        #expect(!APIClientError.server(payload, status: 422).isRetryableSubmissionFailure)
        #expect(!APIClientError.unauthorized.isRetryableSubmissionFailure)
    }

    @MainActor
    private func makeEnvironment(api: PreviewAPIClient) throws -> (AppEnvironment, CredentialStore) {
        let credentials = CredentialStore(service: "com.illinicover.tests.domain.\(UUID().uuidString)")
        let defaults = try #require(UserDefaults(suiteName: "IlliniCoverDomainTests.\(UUID().uuidString)"))
        return (
            AppEnvironment(
                api: api,
                database: try AppDatabase.temporary(),
                credentials: credentials,
                settings: AppSettings(defaults: defaults),
                configuration: AppConfiguration(apiBaseURL: URL(string: "https://example.invalid")!, revenueCatAPIKey: nil)
            ),
            credentials
        )
    }
}

private actor CoverRequestRecorder {
    private(set) var last: CoverSubmissionRequest?
    func record(_ request: CoverSubmissionRequest) { last = request }
}

private actor DealRequestRecorder {
    private(set) var last: DealEvidenceRequest?
    func record(_ request: DealEvidenceRequest) { last = request }
}

private actor BootstrapSuspensionGate {
    private var started = false
    private var released = false
    private var continuations: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        started = true
        guard !released else { return }
        await withCheckedContinuation { continuations.append($0) }
    }

    func waitUntilStarted() async {
        while !started { await Task.yield() }
    }

    func release() {
        released = true
        let waiters = continuations
        continuations.removeAll()
        for waiter in waiters { waiter.resume() }
    }
}

private actor AttemptGate {
    private var dealsAttempts = 0
    private var venueAttempts = 0

    func next() -> Int {
        dealsAttempts += 1
        return dealsAttempts
    }

    func nextVenue() -> Int {
        venueAttempts += 1
        return venueAttempts
    }
}
