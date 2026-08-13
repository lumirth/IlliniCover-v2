import Observation
import SwiftUI

@MainActor
@Observable
private final class HandbookListModel {
    var pages: [HandbookPageSummary] = []
    var isLoading = true
    var isOffline = false
    var errorMessage: String?
    private static let cacheKey = "handbook-list-v2"

    func load(environment: AppEnvironment) async {
        if let cached = try? await environment.database.cached([HandbookPageSummary].self, key: Self.cacheKey) {
            pages = cached.0
            isLoading = false
        }
        do {
            let cached = try? await environment.database.cached([HandbookPageSummary].self, key: Self.cacheKey)
            let result = try await environment.api.handbook(eTag: cached?.1.etag)
            if let pages = result.value {
                self.pages = pages
                try await environment.database.cache(pages, key: Self.cacheKey, etag: result.eTag)
            }
            errorMessage = nil
            isOffline = false
        } catch {
            isOffline = !pages.isEmpty
            errorMessage = pages.isEmpty ? error.localizedDescription : nil
        }
        isLoading = false
    }
}

struct HandbookListView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model = HandbookListModel()

    var body: some View {
        Group {
            if model.isLoading && model.pages.isEmpty {
                ProgressView("Loading handbook…")
            } else if let error = model.errorMessage, model.pages.isEmpty {
                ContentUnavailableView("Handbook unavailable", systemImage: "book.closed", description: Text(error))
            } else {
                List {
                    if model.isOffline { OfflineBanner(text: "Showing the saved handbook.") }
                    ForEach(model.pages) { page in
                        NavigationLink(value: AppRoute.handbookPage(page.slug)) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(page.title).font(.headline)
                                Text(page.summary).font(.subheadline).foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
        }
        .navigationTitle("Handbook")
        .task { await model.load(environment: environment) }
    }
}

@MainActor
@Observable
final class HandbookPageModel {
    var page: HandbookPage?
    var isLoading = true
    var isOffline = false
    var errorMessage: String?

    func load(slug: String, environment: AppEnvironment) async {
        let key = "handbook-page-\(slug)-v2"
        if let cached = try? await environment.database.cached(HandbookPage.self, key: key) {
            page = cached.0
            isLoading = false
        }
        do {
            let page = try await environment.api.handbookPage(slug: slug)
            self.page = page
            try await environment.database.cache(page, key: key, etag: nil)
            isOffline = false
            errorMessage = nil
        } catch {
            if error.isDefinitiveHandbookWithdrawal {
                // A typed 404 means the publisher withdrew this page. Never
                // resurrect it from an older cache; offline/transport errors
                // remain eligible to show the saved copy below.
                page = nil
                isOffline = false
                errorMessage = "This handbook page is no longer available."
                try? await environment.database.removeCache(key: key)
            } else {
                isOffline = page != nil
                errorMessage = page == nil ? error.localizedDescription : nil
            }
        }
        isLoading = false
    }
}

private extension Error {
    var isDefinitiveHandbookWithdrawal: Bool {
        guard let apiError = self as? APIClientError,
              case .server(_, let status) = apiError
        else { return false }
        return status == 404
    }
}

struct HandbookPageView: View {
    @Environment(AppEnvironment.self) private var environment
    let slug: String
    @State private var model = HandbookPageModel()

    var body: some View {
        Group {
            if let page = model.page {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if model.isOffline { OfflineBanner(text: "Showing a saved copy.") }
                        Text(page.summary).font(.title3).foregroundStyle(.secondary)
                        Divider()
                        Text(markdown(page.bodyMarkdown))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                        Text("Updated \(page.updatedAt.formatted(date: .abbreviated, time: .omitted))")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
                    .padding(16)
                }
                .navigationTitle(page.title)
            } else if model.isLoading {
                ProgressView("Loading page…")
            } else {
                ContentUnavailableView("Page unavailable", systemImage: "doc.text.magnifyingglass", description: Text(model.errorMessage ?? "Try again."))
            }
        }
        .task { await model.load(slug: slug, environment: environment) }
    }

    private func markdown(_ source: String) -> AttributedString {
        (try? AttributedString(markdown: source, options: .init(interpretedSyntax: .full))) ?? AttributedString(source)
    }
}
