import SwiftUI
import UIKit

struct VenueShareDescriptor: Equatable {
    let title: String
    let message: String
    let url: URL

    init(venue: Venue) {
        title = venue.name
        message = "\(venue.name) on IlliniCover"
        url = AppDeepLink.venueURL(id: venue.id)
    }

    var fallbackText: String { "\(message)\n\(url.absoluteString)" }
}

struct VenueSharePayload: Identifiable {
    enum Mode: Equatable { case image, link }

    let id = UUID()
    let descriptor: VenueShareDescriptor
    let image: UIImage?

    var mode: Mode { image == nil ? .link : .image }
    var activityItems: [Any] {
        if let image { return [image] }
        return [descriptor.fallbackText, descriptor.url]
    }
}

struct VenueShareActivityView: UIViewControllerRepresentable {
    let payload: VenueSharePayload

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: payload.activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

struct VenueShareSnapshot: View {
    let detail: VenueCoverResponse

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(detail.venue.name)
                .font(.system(size: 36, weight: .bold, design: .rounded))
            if let address = detail.venue.address {
                Label(address, systemImage: "mappin.and.ellipse")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            VStack(spacing: 0) {
                HStack {
                    Text("COVER")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Label(statusLabel, systemImage: statusIcon)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(detail.cover.source == .historical ? ICTheme.estimate : ICTheme.accent)
                }
                Text(detail.cover.price.displayText)
                    .font(.system(size: 64, weight: .bold, design: .rounded))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 18)
                Text(detail.cover.evidenceText)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(20)
            .background(ICTheme.card, in: .rect(cornerRadius: 24, style: .continuous))

            if let report = detail.recentReports.first {
                VStack(alignment: .leading, spacing: 8) {
                    Text("RECENT REPORT")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    HStack {
                        Text(report.price?.displayText ?? "Vibe").font(.title3.bold().monospacedDigit())
                        Spacer()
                        Text(report.observedAt.formatted(.relative(presentation: .named)))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(16)
                .background(ICTheme.card, in: .rect(cornerRadius: 18, style: .continuous))
            }

            Text("IlliniCover")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(ICTheme.accent)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(20)
        .background(ICTheme.background)
    }

    private var statusLabel: String {
        if detail.cover.isAdvertisedConflict { return "Advertised conflict" }
        switch detail.cover.source {
        case .historical: return "Estimate"
        case .advertised: return "Advertised"
        case .mixed: return "Mixed"
        default: return detail.cover.source.label
        }
    }

    private var statusIcon: String {
        switch detail.cover.source {
        case .live: "checkmark.circle.fill"
        case .advertised: "megaphone.fill"
        case .historical: "sparkles"
        case .mixed: "point.3.connected.trianglepath.dotted"
        case .unconfirmed, .unusual: "exclamationmark.triangle.fill"
        case .unavailable: "questionmark.circle.fill"
        }
    }
}

struct BoardSharePayload: Identifiable {
    enum Mode: Equatable { case image, link }

    let id = UUID()
    let image: UIImage?

    var mode: Mode { image == nil ? .link : .image }
    var fallbackText: String { "Bars on IlliniCover\n\(AppDeepLink.barsURL.absoluteString)" }
    var activityItems: [Any] {
        if let image { return [image] }
        return [fallbackText, AppDeepLink.barsURL]
    }
}

struct BoardShareActivityView: UIViewControllerRepresentable {
    let payload: BoardSharePayload

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: payload.activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

/// A stable branded export keeps the board readable when the on-screen list is
/// longer than one viewport. It is intentionally an export composition rather
/// than a second live product surface; taps and evidence actions remain in the
/// real board.
struct BoardShareSnapshot: View {
    let cards: [CoverVenueCard]
    let generatedAt: Date?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Bars")
                        .font(.system(size: 38, weight: .bold, design: .rounded))
                    Text("Cover around campus")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text("IlliniCover")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(ICTheme.accent)
            }

            VStack(spacing: 10) {
                ForEach(cards.prefix(8)) { card in
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(card.venue.name)
                                .font(.headline)
                                .lineLimit(1)
                            Text(card.cover.evidenceText)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 4) {
                            Text(card.cover.price.displayText)
                                .font(.title3.bold().monospacedDigit())
                            Text(card.cover.presentationSourceLabel)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(sourceColor(card.cover))
                        }
                    }
                    .padding(14)
                    .background(ICTheme.card, in: .rect(cornerRadius: 18, style: .continuous))
                }
            }

            if let generatedAt {
                Text("Updated \(generatedAt.formatted(date: .omitted, time: .shortened))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .padding(20)
        .background(ICTheme.background)
    }

    private func sourceColor(_ decision: CoverDecision) -> Color {
        if decision.isAdvertisedConflict { return .orange }
        switch decision.source {
        case .historical: return ICTheme.estimate
        case .unconfirmed, .unusual: return Color.orange
        case .unavailable: return Color.secondary
        default: return ICTheme.accent
        }
    }
}
