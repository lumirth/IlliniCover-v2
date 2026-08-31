import XCTest

final class IlliniCoverUITests: XCTestCase {
    func testPrimaryNavigationIsAccessible() {
        let app = XCUIApplication()
        app.launchArguments = ["-skipOnboarding", "-resetLocalState"]
        app.launch()

        XCTAssertTrue(app.tabBars.buttons["Bars"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.tabBars.buttons["Deals"].exists)
        XCTAssertTrue(app.tabBars.buttons["Settings"].exists)

        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Privacy & Data"].exists)
        XCTAssertTrue(app.staticTexts["Support"].exists)
    }

    func testLiveBackendShowsCoverAndDeals() {
        let app = XCUIApplication()
        app.launchArguments = ["-skipOnboarding", "-resetLocalState"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "cover-venue").firstMatch.waitForExistence(timeout: 15))
        XCTAssertFalse(app.staticTexts["Cover unavailable"].exists)
        app.tabBars.buttons["Deals"].tap()
        XCTAssertTrue(app.navigationBars["Deals"].waitForExistence(timeout: 4))
        XCTAssertFalse(app.staticTexts["Deals unavailable"].exists)
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "deal-offer").firstMatch.waitForExistence(timeout: 10))
    }
}
