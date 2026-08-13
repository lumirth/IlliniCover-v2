# IlliniCover v2

IlliniCover v2 is a native, cover-first iOS application backed by one
Django/PostgreSQL service. It is a clean rebuild beside the pre-alpha v1 app.
The old repository is used only as evidence for intentional product behavior,
visual appearance, historical datasets, and evaluation fixtures.

The governing product and technical requirements are in
[`docs/product/specification.md`](docs/product/specification.md). The server is
the sole owner of evidence assessment, cover and deal resolution, prediction,
same-night nowcasting, and Time Machine reconstruction.

The product's data handling and erasure contract is published in
[`docs/privacy-policy.md`](docs/privacy-policy.md).

## Repository shape

```text
ios/       Native SwiftUI application, GRDB cache/outbox, generated API client
server/    Django, Django Ninja, allauth headless, Admin, jobs, and models
api/       Checked-in generated OpenAPI contract
data/      Versioned source datasets and manifests
docs/      Product, architecture, model receipts, and runbooks
ops/       Container and deployment configuration
```

## Local development

The checked-in setup is being built in vertical slices. See
[`docs/implementation/traceability.md`](docs/implementation/traceability.md)
for the current implementation and verification ledger.
