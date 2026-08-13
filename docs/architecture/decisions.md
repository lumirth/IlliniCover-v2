# Architecture decisions

This ledger records choices required to make the reference specification
executable. Entries are replaceable only through evidence and an explicit new
decision.

## ADR-001 — Clean-room sibling repository

- **Status:** Accepted
- **Decision:** Build v2 at `illinicover-v2` with its own Git history. Preserve
  the supplied specification verbatim. Import reviewed datasets with manifests
  and hashes. Do not copy v1 application or backend implementation.
- **Reason:** The specification explicitly rejects v1's runtime architecture
  while treating its observed behavior and datasets as evidence.

## ADR-002 — Privacy split around immutable observations

- **Status:** Accepted
- **Decision:** Immutable submissions and observation values reference a
  separately erasable private-context record. Exact location, raw network
  metadata, credentials, and account linkages can be deleted or deidentified
  without rewriting the observation itself.
- **Reason:** This satisfies both evidence immutability and account/privacy
  deletion requirements.

## ADR-003 — Idempotency scopes

- **Status:** Accepted
- **Decision:** Every client-originated domain write uses a client UUID.
  Provider-originated writes use the provider's stable event identifier, and
  authentication protocol writes use allauth's protocol semantics and explicit
  rate/attempt controls.
- **Reason:** Provider webhooks and authentication exchanges cannot carry a
  client-generated submission UUID, but still require replay safety.

## ADR-004 — Deferred product choices

- **Status:** Accepted
- **Decision:** Android, advanced CMS, queues, automated social extraction,
  Sign in with Apple, and speculative context features are not v2 beta scope.
  Exact cover and deal models, horizons, thresholds, and free-history limits
  must be selected from checked-in evaluation receipts rather than guessed.
- **Reason:** These are explicitly deferred by the specification.
