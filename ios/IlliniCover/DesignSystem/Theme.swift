import SwiftUI

enum ICTheme {
    static let accent = Color(red: 10 / 255, green: 132 / 255, blue: 1)
    static let estimate = Color(light: Color(red: 124 / 255, green: 58 / 255, blue: 237 / 255), dark: Color(red: 191 / 255, green: 90 / 255, blue: 242 / 255))
    static let right = Color(light: Color(red: 4 / 255, green: 120 / 255, blue: 87 / 255), dark: Color(red: 50 / 255, green: 215 / 255, blue: 75 / 255))
    static let wrong = Color(light: Color(red: 185 / 255, green: 28 / 255, blue: 28 / 255), dark: Color(red: 1, green: 69 / 255, blue: 58 / 255))
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let background = Color(uiColor: .systemGroupedBackground)
    static let secondary = Color(uiColor: .secondaryLabel)
}

private extension Color {
    init(light: Color, dark: Color) {
        self.init(uiColor: UIColor { traits in
            UIColor(traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

struct ActionPillStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 12)
            .frame(minHeight: 44)
            .background(color.opacity(configuration.isPressed ? 0.28 : 0.18), in: .capsule)
            .contentShape(.rect)
    }
}

struct PrimaryActionStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(ICTheme.accent.opacity(configuration.isPressed ? 0.72 : 1), in: .rect(cornerRadius: 14))
    }
}

struct StatusPill: View {
    let text: String
    var color: Color = .secondary

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .lineLimit(1)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(color.opacity(0.1), in: .capsule)
    }
}

struct OfflineBanner: View {
    let text: String

    var body: some View {
        Label(text, systemImage: "wifi.slash")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 9)
            .background(.thinMaterial)
            .accessibilityIdentifier("offline-banner")
    }
}
