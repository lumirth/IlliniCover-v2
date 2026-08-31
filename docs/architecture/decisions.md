# Architecture decisions

The product specification owns behavior. These decisions describe the smallest
current implementation and may be replaced while the product remains pre-alpha.

## Pre-alpha reset

The current schema, API, local cache, and canonical datasets replace their earlier
forms outright. There are no compatibility aliases, historical migration chains, or
dual-read/write periods. Git retains anything we later discover was useful.

## Privacy boundary

Observation values are durable. Credentials, account links, exact location, and
network context are separately erasable. Privacy deletion must be a direct indexed
operation, not a scan through logs, sessions, or serialized provider payloads.

## Idempotency

Client writes use a client UUID and database uniqueness. Provider events use the
provider event identifier. Authentication uses allauth's protocol. The application
does not create generic operation receipts or payload fingerprints around those
native guarantees.

## Model authority

The deployed application revision contains the single cover and deal model behavior.
Candidates are evaluated offline. Deployment and rollback use the platform's normal
application revision mechanism; there is no runtime model-release control plane.

## Deferred systems

Android, advanced CMS, queues, social extraction, speculative context sources, and
generalized evidence or synchronization frameworks do not exist until a shipped
feature requires them.
