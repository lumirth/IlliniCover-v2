# IlliniCover

IlliniCover is a native SwiftUI app backed by one Django/PostgreSQL service.
The server owns cover and deal interpretation; the client owns presentation,
local cache, and an offline submission outbox.

The authority order is:

1. [`docs/product/specification.md`](docs/product/specification.md) for product behavior;
2. [`docs/architecture/decisions.md`](docs/architecture/decisions.md) for implementation choices the specification leaves open; and
3. tests for executable invariants.

The public data-handling contract is
[`docs/privacy-policy.md`](docs/privacy-policy.md).

## Repository

```text
ios/      Checked-in Xcode project and native client
server/   Django application, migrations, and tests
api/      Checked-in OpenAPI contract
data/     Canonical venue, cover, and deal JSONL
ops/      Container and immutable Cloud Run deployment
scripts/  Local and CI entrypoints
docs/     Product, architecture, operations, and acceptance
```

## Start locally

```bash
mise install
mise run setup
mise run up
```

`setup` installs the locked dependencies, starts loopback PostgreSQL, applies
migrations, and idempotently loads the canonical data. `up` serves Django at
`http://127.0.0.1:8000`.

In another terminal, set `ILLINICOVER_SIMULATOR_UDID` to a dedicated Simulator
and run:

```bash
mise run ios:boot
mise run ios:build
ILLINICOVER_TEST_PLAN=Integration mise run ios:test
```

See [`docs/operations/README.md`](docs/operations/README.md) for CI, deployment,
secrets, rollback, restore, and RevenueCat recovery. See
[`docs/runbooks/runtime-acceptance.md`](docs/runbooks/runtime-acceptance.md) for
the release evidence contract.
