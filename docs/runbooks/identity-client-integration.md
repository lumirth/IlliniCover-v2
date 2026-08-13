# Identity client integration

IlliniCover uses django-allauth headless 65.19.0 in app-only mode. The mobile
client stores every session token in Keychain and supplies it in the
`X-Session-Token` header. The backend token strategy never uses a Django
session key as the bearer token: clients receive a separate high-entropy token
and PostgreSQL stores only its HMAC-SHA256 verifier.

## Existing-account email code

1. `POST /_allauth/app/v1/auth/code/request` with JSON `{ "email": "..." }`.
2. Expect HTTP 401 while the flow is pending. Read
   `meta.session_token` from the response and persist it immediately. A pending
flow appears in `data.flows` as `login_by_code`.
3. `POST /_allauth/app/v1/auth/code/confirm` with JSON `{ "code": "..." }`
   and the pending token in `X-Session-Token`. Do not repeat the email in this
   request.
4. On HTTP 200, read the account from `data.user` and replace the pending token
   with the rotated `meta.session_token`.

Allauth may rotate the pending token on resend and on a rejected code. Persist
any replacement `meta.session_token` before interpreting the HTTP status so the
next resend or verification attempt uses the current challenge credential.

An unknown email follows allauth's non-enumerating response path and does not
silently create an account.

The default allauth code is eight unambiguous consonants shown as `XXXX-XXXX`.
The confirm endpoints ignore spacing and punctuation, but the client should
display the code exactly as received.

## New account

1. `POST /_allauth/app/v1/auth/signup` with JSON `{ "email": "..." }`.
   Password is absent by configuration.
2. Expect HTTP 401 with a pending `verify_email` flow and persist
   `meta.session_token`.
3. `POST /_allauth/app/v1/auth/email/verify` with JSON `{ "key": "..." }`
   and the pending token in `X-Session-Token`.
4. On HTTP 200, replace the pending token with the new
   `meta.session_token` and use `data.user.id` as the stable account UUID.

## Session lifecycle

- `GET /_allauth/app/v1/auth/session` with `X-Session-Token` reads session
  state.
- `DELETE /_allauth/app/v1/auth/session` logs out and revokes the current
  token through the session lifecycle. Send the current installation token as
  `X-Installation-Token` too. When it belongs to the authenticated account,
  logout deactivates that installation's account attribution: subsequent
  reports remain owned by the durable privacy link but are recorded with no
  `account_id` and no signed-in trust signal.
- Retrying any previously accepted link request for the same actor/account
  reactivates account attribution. Logout never transfers or deletes the
  durable actor/account link; account deletion still uses it to erase every
  linked actor context, including reports made while attribution was inactive.
- `GET /api/v2/me`, `/api/v2/me/entitlements`, and protected Time Machine
  requests use the same `X-Session-Token`.
- `POST /api/v2/cover-submissions` and `POST /api/v2/deal-evidence` always
  require `X-Installation-Token` and accept `X-Session-Token` as an optional
  per-request attribution credential. Send the current session token when one
  exists. The server records account association and signed-in trust only when
  that session is valid and belongs to the installation's active durable link.
  A missing, expired, inactive-link, or different-account session is accepted
  as a guest submission and is never attributed across accounts.
- A 410 from allauth means the token is expired, revoked, or otherwise gone;
  remove it from Keychain.

Response keys in allauth's protocol use `snake_case`. IlliniCover's `/api/v2`
product contract uses `camelCase`.

## Installation issuance and rotation

Every installation write uses a persisted client UUID. Generate installation
tokens on-device as `ic_install_` followed by the unpadded base64url encoding of
32 cryptographically random bytes. Persist the request UUID and raw token in
Keychain before sending either request; PostgreSQL stores only an HMAC-SHA256
verifier.

- Create with `POST /api/v2/installations` and
  `{ "requestId": "uuid-v4", "installationToken": "ic_install_..." }`.
- Rotate with `POST /api/v2/installations/rotate`, the current credential in
  `X-Installation-Token`, and
  `{ "requestId": "uuid-v4", "replacementInstallationToken": "ic_install_..." }`.
- Link with `POST /api/v2/me/link-installation` and a stable `requestId` beside
  `installationToken`. Each successful request UUID is reserved durably for
  that exact actor/account link, including a new UUID sent after the actor was
  already linked to the same account. Retrying that UUID returns the same link;
  reusing it for another actor or account fails closed.

Create and rotate return the request UUID, stable actor UUID, and the
client-supplied token. Repeating the same UUID and token returns the same actor.
Reusing either identifier with conflicting data fails closed. Issuance is also
bounded by a PostgreSQL-backed per-network limit before it allocates a new
actor.

Rotation checks a completed receipt before authenticating the current token.
After a lost success response, retry the same request UUID and replacement
token; the header may contain the replacement token because the old actor and
credential were atomically erased. Never create a second replacement token for
the same request UUID.

Link receipts contain only the random request UUID, link reference, and
completion time. They live exactly as long as the actor/account link rather
than expiring independently: actor rotation or account deletion cascades the
link and all of its receipts, preventing them from preserving a deleted-user
pseudonym.

## Account-deletion recovery

Before `DELETE /api/v2/me`, persist a UUID-v4 and send it as
`{ "requestId": "..." }`. The deletion and its completion receipt commit in one
database transaction. The receipt contains only the random request UUID and
completion/expiry timestamps: it has no account, actor, email, session, or
provider linkage.

If the authenticated response is lost, query the unauthenticated
`GET /api/v2/account-deletions/{requestId}` endpoint. HTTP 200 proves the exact
deletion request completed; HTTP 404 means no unexpired completion receipt
exists and must not be treated as success. The client should retain the pending
UUID until it receives proof.

Receipts are retained for 30 days by default, long enough for an offline beta
client to recover from response loss without preserving a deleted-user
pseudonym indefinitely. The nightly cleanup deletes expired receipts. Account
deletion also deletes every linked installation actor, verifier-only
credential, and issuance receipt after deidentifying durable observations, so
the client must provision a fresh guest installation after completion.
