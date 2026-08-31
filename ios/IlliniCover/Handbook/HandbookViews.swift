import SwiftUI

struct HandbookListView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var pages: [HandbookPageSummary] = []
    @State private var loading = true
    @State private var offline = false
    @State private var error: String?

    var body: some View {
        Group {
            if loading && pages.isEmpty { ProgressView("Loading handbook…") }
            else if let error, pages.isEmpty { ContentUnavailableView("Handbook unavailable", systemImage: "book.closed", description: Text(error)) }
            else {
                List {
                    if offline { OfflineBanner(text: "Showing the saved handbook.") }
                    ForEach(pages) { page in
                        NavigationLink { HandbookPageView(slug: page.slug) } label: {
                            VStack(alignment: .leading) { Text(page.title).font(.headline); Text(page.summary).font(.subheadline).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
        .navigationTitle("Handbook")
        .task { await load() }
    }

    private func load() async {
        if let cached = try? await environment.database.cached([HandbookPageSummary].self, key: "handbook") { pages = cached.0; loading = false; offline = true }
        do { pages = try await environment.api.handbook(); try await environment.database.cache(pages, key: "handbook"); offline = false }
        catch { self.error = pages.isEmpty ? error.localizedDescription : nil }
        loading = false
    }
}

struct HandbookPageView: View {
    @Environment(AppEnvironment.self) private var environment
    let slug: String
    @State private var page: HandbookPage?
    @State private var offline = false
    @State private var error: String?

    var body: some View {
        Group {
            if let page {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if offline { OfflineBanner(text: "Showing a saved copy.") }
                        Text(page.summary).font(.title3).foregroundStyle(.secondary)
                        Divider()
                        Text((try? AttributedString(markdown: page.bodyMarkdown)) ?? AttributedString(page.bodyMarkdown)).textSelection(.enabled)
                    }.padding()
                }.navigationTitle(page.title)
            } else if let error { ContentUnavailableView("Page unavailable", systemImage: "doc.text.magnifyingglass", description: Text(error)) }
            else { ProgressView() }
        }
        .task { await load() }
    }

    private func load() async {
        let key = "handbook-\(slug)"
        if let cached = try? await environment.database.cached(HandbookPage.self, key: key) { page = cached.0; offline = true }
        do { let value = try await environment.api.handbookPage(slug); page = value; try await environment.database.cache(value, key: key); offline = false }
        catch { self.error = page == nil ? error.localizedDescription : nil }
    }
}
