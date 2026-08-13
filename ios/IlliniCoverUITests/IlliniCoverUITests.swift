import XCTest

@MainActor
final class IlliniCoverUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPrimaryTabsAndReportSheet() throws {
        let app = launch(skipOnboarding: true)
        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.buttons["bar-card-live"].exists)

        let wrong = app.buttons["Report a different cover price at KAMS"]
        XCTAssertTrue(wrong.waitForExistence(timeout: 3))
        wrong.tap()
        XCTAssertTrue(reportHeader("Adjust, KAMS", in: app).waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["cover-report-submit"].isEnabled)
        app.buttons["cover-quick-500"].tap()
        XCTAssertTrue(app.buttons["cover-report-submit"].isEnabled)
        app.buttons["cover-report-submit"].tap()
        XCTAssertTrue(reportHeader("Adjust, KAMS", in: app).waitForNonExistence(timeout: 4))
        XCTAssertTrue(app.navigationBars["Bars"].exists)

        app.tabBars.buttons["Deals"].tap()
        XCTAssertTrue(app.navigationBars["Deals"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["White Claw"].exists)
        XCTAssertTrue(app.buttons["Open KAMS, 1 deals"].exists)
        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["IlliniCover Blue"].exists)
    }

    func testIlliniCoverBluePaywallHierarchyAndTerms() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "-uiTesting",
            "-resetUITestState",
            "-skipOnboarding",
            "-signedInFree",
        ]
        app.launch()

        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 8))
        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 3))
        app.buttons["illinicover-blue-settings"].tap()

        XCTAssertTrue(app.navigationBars["IlliniCover Blue"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Know before you go."].exists)

        XCTAssertTrue(app.buttons["Annual, Best subscription value, $12.99 / year, Renews yearly until canceled."].exists)
        XCTAssertTrue(app.buttons["Monthly, $1.99 / month, Renews monthly until canceled."].exists)
        XCTAssertFalse(app.staticTexts["Weekly"].exists)
        XCTAssertFalse(app.staticTexts["Six months"].exists)
        XCTAssertFalse(app.staticTexts["Lifetime"].exists)

        app.buttons["Show more options"].tap()
        XCTAssertTrue(app.buttons["Weekly, $0.99 / week, Renews weekly until canceled."].waitForExistence(timeout: 3))
        let lifetime = app.buttons["Lifetime, $24.99 once, One-time purchase. No renewal."]
        app.swipeUp()
        XCTAssertTrue(app.buttons["Six months, $7.99 / 6 months, Renews every six months until canceled."].exists)
        XCTAssertTrue(lifetime.waitForExistence(timeout: 3))
        app.swipeUp()
        XCTAssertTrue(app.buttons["Restore Purchases"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.links["Manage Apple Subscriptions"].exists)
        app.swipeUp()
        XCTAssertTrue(app.descendants(matching: .any)["blue-terms-of-use"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS '$rc_'"))
            .firstMatch.exists)
    }

    func testIlliniCoverBluePendingConfirmationSuppressesAnotherPurchase() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "-uiTesting",
            "-resetUITestState",
            "-skipOnboarding",
            "-signedInFree",
            "-blueConfirmationPending",
        ]
        app.launch()

        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 8))
        app.tabBars.buttons["Settings"].tap()
        app.buttons["illinicover-blue-settings"].tap()

        XCTAssertTrue(app.descendants(matching: .any)["blue-confirmation-pending"]
            .waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["blue-confirmation-refresh"].exists)
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Annual,'"))
            .firstMatch.exists)
        XCTAssertFalse(app.buttons["Restore Purchases"].exists)
    }

    func testIlliniCoverBlueLifetimeOwnerIsNotSentToSubscriptionManagement() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "-uiTesting",
            "-resetUITestState",
            "-skipOnboarding",
            "-signedIn",
            "-blueLifetimeOwned",
        ]
        app.launch()

        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 8))
        app.tabBars.buttons["Settings"].tap()
        app.buttons["illinicover-blue-settings"].tap()

        XCTAssertTrue(app.staticTexts["IlliniCover Blue is active"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.links["Manage Apple Subscriptions"].exists)
    }

    func testOnboardingAndEmailCode() throws {
        let app = launch(skipOnboarding: false)
        XCTAssertTrue(app.staticTexts["IlliniCover"].waitForExistence(timeout: 8))
        app.buttons["onboarding-email"].tap()
        let email = app.textFields["email-address"]
        XCTAssertTrue(email.waitForExistence(timeout: 3))
        email.tap()
        email.typeText("alex@example.com")
        app.buttons["sign-in-submit"].tap()
        let code = app.textFields["email-code"]
        XCTAssertTrue(code.waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["resend-code"].isEnabled)
        app.buttons["resend-code"].tap()
        XCTAssertTrue(app.staticTexts["A new code was sent."].waitForExistence(timeout: 3))
        code.tap()
        code.typeText("BCDFGHJK")
        app.buttons["sign-in-submit"].tap()
        XCTAssertTrue(app.staticTexts["Location adds context"].waitForExistence(timeout: 4))
    }

    func testOnboardingSignInCancelReturnsToWelcomeAndAbandonsCodeStep() throws {
        let app = launch(skipOnboarding: false)
        XCTAssertTrue(app.buttons["onboarding-email"].waitForExistence(timeout: 8))
        app.buttons["onboarding-email"].tap()
        let email = app.textFields["email-address"]
        XCTAssertTrue(email.waitForExistence(timeout: 3))
        email.tap()
        email.typeText("alex@example.com")
        app.buttons["sign-in-submit"].tap()
        XCTAssertTrue(app.textFields["email-code"].waitForExistence(timeout: 3))

        app.buttons["sign-in-cancel"].tap()
        XCTAssertTrue(app.buttons["onboarding-email"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.textFields["email-code"].exists)

        app.buttons["onboarding-email"].tap()
        XCTAssertTrue(app.textFields["email-address"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.textFields["email-code"].exists)
    }

    func testBarContextMenu() throws {
        let app = launch(skipOnboarding: true)
        let card = app.buttons["bar-card-live"]
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        card.press(forDuration: 1.1)
        XCTAssertTrue(app.buttons["Open details"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["Report right price"].exists)
        XCTAssertTrue(app.buttons["Report wrong price"].exists)
    }

    func testOrdinaryRightAndCardMenuRightOpenConfirmSheet() throws {
        let app = launch(skipOnboarding: true)
        let right = app.buttons["Confirm 10 dollar cover at KAMS"]
        XCTAssertTrue(right.waitForExistence(timeout: 8))
        right.tap()
        XCTAssertTrue(reportHeader("Confirm, KAMS", in: app).waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["cover-report-submit"].isEnabled)
        app.buttons["Cancel"].tap()

        let card = app.buttons["bar-card-live"]
        card.press(forDuration: 1.1)
        app.buttons["Report right price"].tap()
        XCTAssertTrue(reportHeader("Confirm, KAMS", in: app).waitForExistence(timeout: 3))
    }

    func testQuickMenusPreserveExactHierarchyAndCopy() throws {
        let app = launch(skipOnboarding: true)
        let right = app.buttons["Confirm 10 dollar cover at KAMS"]
        XCTAssertTrue(right.waitForExistence(timeout: 8))
        right.press(forDuration: 1.1)
        XCTAssertTrue(app.buttons["Quick confirm"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Quick confirm $'")).firstMatch.exists)
        app.tap()

        let wrong = app.buttons["Report a different cover price at KAMS"]
        wrong.press(forDuration: 1.1)
        for amount in ["$0", "$5", "$10", "$20"] {
            XCTAssertTrue(app.buttons["Quick report \(amount)"].waitForExistence(timeout: 3))
        }
        XCTAssertFalse(app.buttons["Other Price…"].exists)
    }

    func testManualCoverEditorCancelDoneAndHighPriceAlert() throws {
        let app = launch(skipOnboarding: true)
        app.buttons["Report a different cover price at KAMS"].tap()
        XCTAssertTrue(reportHeader("Adjust, KAMS", in: app).waitForExistence(timeout: 3))
        app.buttons["cover-price-manual"].tap()
        let editor = app.textFields["cover-price-editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["cover-report-submit"].isEnabled)
        editor.clearAndType("45")
        expectation(for: NSPredicate(format: "value == '45'"), evaluatedWith: editor)
        waitForExpectations(timeout: 3)
        app.buttons["cover-price-keyboard-done"].tap()
        let submit = app.buttons["cover-report-submit"]
        expectation(for: NSPredicate(format: "isEnabled == true"), evaluatedWith: submit)
        waitForExpectations(timeout: 3)
        submit.tap()
        XCTAssertTrue(app.alerts["Report $45?"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.alerts["Report $45?"].staticTexts["That is an unusually high cover. Please double-check that it is $45."].exists)
        XCTAssertTrue(app.alerts["Report $45?"].buttons["Cancel"].exists)
        XCTAssertTrue(app.alerts["Report $45?"].buttons["Report $45"].exists)
    }

    func testClearedMaximumCoverReenablesBothPriceDirections() throws {
        let app = launch(skipOnboarding: true)
        app.buttons["Report a different cover price at KAMS"].tap()
        XCTAssertTrue(reportHeader("Adjust, KAMS", in: app).waitForExistence(timeout: 3))
        app.buttons["cover-price-manual"].tap()
        let editor = app.textFields["cover-price-editor"]
        XCTAssertTrue(editor.waitForExistence(timeout: 3))
        editor.clearAndType("70")
        app.buttons["cover-price-done"].tap()
        app.buttons["cover-price-clear"].tap()
        let increase = app.buttons["Increase cover by five dollars"]
        let decrease = app.buttons["Decrease cover by five dollars"]
        XCTAssertTrue(increase.isEnabled)
        XCTAssertTrue(decrease.isEnabled)
        increase.tap()
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "value == '$5'")).count, 1)
    }

    func testPremiumTimeMachineWithAuthenticatedFixture() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTesting", "-resetUITestState", "-skipOnboarding", "-signedIn"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 8))
        app.buttons["bar-card-live"].tap()
        XCTAssertTrue(app.navigationBars["KAMS"].waitForExistence(timeout: 3))
        app.buttons["Open Time Machine"].tap()
        XCTAssertTrue(app.navigationBars["Time Machine"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Current assessment"].waitForExistence(timeout: 4))
    }

    func testNewDealAutoPresentsFocusedSearchOnlyOnce() throws {
        let app = launch(skipOnboarding: true)
        app.tabBars.buttons["Deals"].tap()
        XCTAssertTrue(app.navigationBars["Deals"].waitForExistence(timeout: 3))
        let addDeal = app.buttons.matching(NSPredicate(format: "label == 'Add Deal'")).firstMatch
        XCTAssertTrue(addDeal.waitForExistence(timeout: 3))
        addDeal.tap()
        XCTAssertTrue(app.textFields["deal-search-field"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.keyboards.element.waitForExistence(timeout: 3))
        app.buttons["deal-search-close"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["deal-composer-header"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.textFields["deal-search-field"].exists)

        let timing = app.buttons["deal-timing-menu"]
        let serving = app.buttons["deal-serving-menu"]
        XCTAssertTrue(timing.waitForExistence(timeout: 3))
        XCTAssertTrue(serving.exists)
        XCTAssertLessThan(timing.frame.midX, serving.frame.midX)
    }

    func testBarStatusSurfaceOpensDetailsWithoutStealingRightWrongActions() throws {
        let app = launch(skipOnboarding: true)
        let card = app.buttons["bar-card-live"]
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        let lowerStatusPoint = card.coordinate(withNormalizedOffset: CGVector(dx: 0.86, dy: 0.86))
        lowerStatusPoint.tap()
        XCTAssertTrue(app.navigationBars["KAMS"].waitForExistence(timeout: 3))
    }

    func testPersistedPrivacyTransitionHidesCachedProductSurfaces() throws {
        let seed = XCUIApplication()
        seed.launchArguments = ["-uiTesting", "-resetUITestState", "-skipOnboarding", "-seedPrivacyTransition"]
        seed.launch()
        XCTAssertTrue(seed.descendants(matching: .any)["privacy-transition-gate"].waitForExistence(timeout: 8))
        XCTAssertTrue(seed.staticTexts["Account deletion pending"].exists)
        XCTAssertFalse(seed.navigationBars["Bars"].exists)
        XCTAssertFalse(seed.navigationBars["Deals"].exists)
        XCTAssertFalse(seed.tabBars.buttons["Bars"].exists)
        XCTAssertFalse(seed.buttons["bar-card-live"].exists)
        XCTAssertFalse(seed.staticTexts["White Claw"].exists)
        XCTAssertTrue(seed.buttons["privacy-transition-sign-in"].exists)
        seed.buttons["privacy-transition-sign-in"].tap()
        XCTAssertTrue(seed.navigationBars["Finish Deletion"].waitForExistence(timeout: 3))
        XCTAssertTrue(seed.staticTexts["Sign in only to the same account that requested deletion. A different account will never be deleted."].exists)
        seed.buttons["Cancel"].tap()
        XCTAssertTrue(seed.descendants(matching: .any)["privacy-transition-gate"].waitForExistence(timeout: 3))
        XCTAssertFalse(seed.tabBars.buttons["Bars"].exists)
    }

    func testPendingDeletionRejectsDifferentAccount() throws {
        // Original-account recovery is covered deterministically by
        // PrivacyLifecycleTests. This UI case owns the visible, fail-closed
        // mismatch state without racing the fixture's deliberate first
        // offline deletion attempt during bootstrap.
        let mismatch = XCUIApplication()
        mismatch.launchArguments = ["-uiTesting", "-resetUITestState", "-skipOnboarding", "-seedMismatchedPrivacyTransition"]
        mismatch.launch()
        finishDeletionSignIn(in: mismatch)
        XCTAssertTrue(mismatch.navigationBars["Finish Deletion"].waitForExistence(timeout: 4))
        let mismatchError = mismatch.descendants(matching: .any)["sign-in-error"]
        XCTAssertTrue(mismatchError.waitForExistence(timeout: 4))
        XCTAssertEqual(
            mismatchError.label,
            "Sign in to the same account that requested deletion. IlliniCover did not delete the account you just signed in to."
        )
        XCTAssertTrue(mismatch.descendants(matching: .any)["privacy-transition-gate"].exists)
        XCTAssertFalse(mismatch.tabBars.buttons["Bars"].exists)
    }

    /// Deliberately omitted from the fast fixture plan. The Integration plan
    /// launches the app's LiveAPIClient against loopback Django/PostgreSQL and
    /// proves the generated transport reaches settled product UI.
    func testLiveAcceptanceGeneratedClientSmoke() throws {
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["ILLINICOVER_INTEGRATION"] == "1",
            "Run with TestPlans/Integration.xctestplan and local Django/PostgreSQL."
        )
        let app = XCUIApplication()
        app.launchArguments = ["-liveAcceptance", "-skipOnboarding", "-resetLiveAcceptance"]
        app.launch()

        XCTAssertTrue(app.navigationBars["Bars"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["bar-card-kams"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.staticTexts["KAMS"].exists)
        app.tabBars.buttons["Deals"].tap()
        XCTAssertTrue(app.navigationBars["Deals"].waitForExistence(timeout: 5))
        let dealVenue = app.buttons.matching(
            NSPredicate(format: "label MATCHES %@", #"^Open .+, [0-9]+ deals$"#)
        ).firstMatch
        XCTAssertTrue(dealVenue.waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["environment-marker"].exists)
    }

    private func launch(skipOnboarding: Bool) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "-uiTesting",
            "-resetUITestState",
            skipOnboarding ? "-skipOnboarding" : "-resetOnboarding",
        ]
        app.launch()
        return app
    }

    private func reportHeader(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: "cover-report-header")
            .matching(NSPredicate(format: "label == %@", label))
            .firstMatch
    }

    private func finishDeletionSignIn(in app: XCUIApplication) {
        XCTAssertTrue(app.buttons["privacy-transition-sign-in"].waitForExistence(timeout: 8))
        app.buttons["privacy-transition-sign-in"].tap()
        let email = app.textFields["email-address"]
        XCTAssertTrue(email.waitForExistence(timeout: 3))
        email.tap()
        email.typeText("alex@example.com")
        app.buttons["sign-in-submit"].tap()
        let code = app.textFields["email-code"]
        XCTAssertTrue(code.waitForExistence(timeout: 3))
        code.tap()
        code.typeText("BCDFGHJK")
        app.buttons["sign-in-submit"].tap()
    }
}

private extension XCUIElement {
    func clearAndType(_ text: String) {
        doubleTap()
        typeText(text)
    }
}
