import Foundation
import Testing

@Suite("App privacy manifest")
struct PrivacyManifestTests {
    @Test("The bundled manifest declares app data and the app-only UserDefaults reason")
    func bundledManifest() throws {
        let url = try #require(Bundle.main.url(forResource: "PrivacyInfo", withExtension: "xcprivacy"))
        let data = try Data(contentsOf: url)
        let plist = try #require(
            PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        )

        #expect(plist["NSPrivacyTracking"] as? Bool == false)

        let accessed = try #require(plist["NSPrivacyAccessedAPITypes"] as? [[String: Any]])
        let userDefaults = try #require(accessed.first {
            $0["NSPrivacyAccessedAPIType"] as? String == "NSPrivacyAccessedAPICategoryUserDefaults"
        })
        #expect(userDefaults["NSPrivacyAccessedAPITypeReasons"] as? [String] == ["CA92.1"])

        let collected = try #require(plist["NSPrivacyCollectedDataTypes"] as? [[String: Any]])
        let types = Set(collected.compactMap { $0["NSPrivacyCollectedDataType"] as? String })
        #expect(types == [
            "NSPrivacyCollectedDataTypeName",
            "NSPrivacyCollectedDataTypeEmailAddress",
            "NSPrivacyCollectedDataTypePreciseLocation",
            "NSPrivacyCollectedDataTypeUserID",
            "NSPrivacyCollectedDataTypeDeviceID",
            "NSPrivacyCollectedDataTypePurchaseHistory",
            "NSPrivacyCollectedDataTypeOtherUserContent",
            "NSPrivacyCollectedDataTypeCustomerSupport",
            "NSPrivacyCollectedDataTypeProductInteraction",
            "NSPrivacyCollectedDataTypeOtherDataTypes",
        ])

        for declaration in collected {
            #expect(declaration["NSPrivacyCollectedDataTypeLinked"] as? Bool == true)
            #expect(declaration["NSPrivacyCollectedDataTypeTracking"] as? Bool == false)
            #expect(
                declaration["NSPrivacyCollectedDataTypePurposes"] as? [String]
                    == ["NSPrivacyCollectedDataTypePurposeAppFunctionality"]
            )
        }
    }
}
