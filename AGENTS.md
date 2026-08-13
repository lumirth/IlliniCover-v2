# IlliniCover v2 agent guide

The product specification in `docs/product/specification.md` owns required
behavior. `docs/architecture/decisions.md` owns implementation decisions that
the specification deliberately leaves open. Tests own executable invariants.

## Boundaries

- `ios/` is native Swift/SwiftUI. Do not introduce React Native, Expo, a shared
  JavaScript runtime, presenter layers, route metadata, TCA, or generic DI.
- `server/` is one Django application. Django ORM is the default data-access
  layer. Add a service only for a real use case or transaction.
- Clients never connect to PostgreSQL and never reproduce server domain logic.
- Cover and deals share infrastructure and actor context, not interpretation.
- Preserve observations and provenance. A derived decision is never evidence.
- Historical datasets are versioned imports, never schema migrations.

## Workflow

- Preserve unrelated work and inspect final status/diff.
- Use the smallest verification lane that proves a change.
- Runtime acceptance requires install, launch, settled UI/accessibility,
  screenshots, and bounded logs; a build alone is insufficient.
- Never commit secrets, exact private location, OTPs, or provider credentials.
