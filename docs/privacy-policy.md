# IlliniCover privacy policy

Last updated: August 30, 2026

IlliniCover collects the minimum information needed to accept community reports,
provide optional accounts and IlliniCover Blue, prevent abuse, and improve cover and
deal estimates. It does not sell personal information or use it for advertising or
cross-app tracking.

## Reports and location

You may browse and report without an account. Reports contain the venue, observed
time, reported cover/vibes/deal information, interaction context, and a random
installation identity. The server also records when it received the report so an
offline upload cannot appear newly fresh.

Location is optional and requested only while you intentionally submit a report. If
you provide it, IlliniCover stores latitude, longitude, accuracy and observation time
in restricted private context to assess proximity, data quality and impossible travel.
Missing location does not count against a report. IlliniCover does not continuously
track location.

Public APIs and report history never expose exact location, installation/account/device
identifiers, credentials, network metadata or internal abuse reasons. They may show
only deidentified evidence such as venue, reported value, approximate age and broad
inside/outside context.

## Installations, accounts and purchases

An installation uses a random high-entropy credential so reporting and offline retry
work without an account. The app keeps raw installation and account-session secrets in
iOS Keychain; the server keeps secure verifiers rather than raw installation tokens.

Optional accounts use a verified email and short-lived django-allauth email code. An
account may link several installations. Email is a credential, not the stable account
identifier. IlliniCover Blue purchases use the non-guessable account UUID as RevenueCat
App User ID; RevenueCat mirrors purchase and entitlement state to the server.

The server may derive a one-way keyed value from the requester address for bounded
rate limiting and abuse correlation. It does not put the raw address into observation
records or treat network location as proof that somebody was at a venue.

## Service providers and telemetry

IlliniCover uses Google Cloud Run and Neon to host the application and database,
RevenueCat for purchases and entitlement state, an email provider for requested login
codes, and Sentry only when error monitoring is configured. Providers receive only the
information needed to perform those functions and remain subject to their own secured
access and retention controls.

Application logs and error reports use a small safe allowlist such as environment,
code revision, generalized route, validated request ID, exception type and stack
locations. Request/report bodies, authentication values, cookies, arbitrary headers,
query strings, exact location, user identity, screenshots, session replay and local
variables are not intentionally sent to application telemetry. Infrastructure
providers may retain ordinary request/security metadata under their configured
operational retention policies; IlliniCover does not copy that metadata into public
evidence.

## Retention and deletion

Accepted observation values and useful source provenance may remain as deidentified
evidence. Private context—credentials, account links, exact location, network
correlation, session state and provider identifiers—is kept separately so it can be
removed without rewriting what was observed.

Deleting an account synchronously removes the account, verified email, active sessions,
installation links, private report context and local premium authorization. It also
requests deletion of the RevenueCat customer. If that provider request is temporarily
unavailable, the server retains only the minimum pending deletion work needed to retry;
successful provider-deletion work is removed.

Guest installation rotation/delete removes that installation's credential, links and
private report context. Retained observations must not contain a stable deleted-user
pseudonym, exact location, raw network identity, email or RevenueCat identity.

There are no installation-link receipts, account-deletion recovery receipts, persisted
cover-decision receipts, model-release records or fixture/evidence archives containing
personal data. A lost account-deletion response that later returns unauthorized is
treated by the app as already deleted. A lost installation-creation/rotation response
may leave an empty orphan installation with no observations; bounded maintenance may
remove unused actors.

Database backups and provider security/audit logs follow restricted operational
retention and restore procedures. Restored data remains subject to the same deletion
and access restrictions before normal service resumes.

## Your choices

You can:

- browse and report without an email;
- omit location;
- delete an account and its private linkage; or
- rotate/delete a guest installation and its private context.

When **Report a Problem** is configured, the app opens a mail draft that you review
before sending. It includes only text you choose plus basic app/iOS context; it does
not automatically attach report payloads, location or credentials. Support mail is
restricted to support/security work and removed when no longer needed, subject to a
legal or security preservation requirement.

Before external beta, the support contact, public policy URL, App Store privacy answers
and iOS privacy manifest must match this policy and the running application.
