# IlliniCover privacy policy

Last updated: August 12, 2026

IlliniCover collects the minimum information needed to accept community reports,
show account and premium state, prevent abuse, and improve evidence-bounded cover
and deal predictions.

## Location and reports

Location is optional and is requested only while you intentionally submit a
report. When you provide it, IlliniCover stores the submitted latitude,
longitude, accuracy, observation time, and report context so the server can
assess venue proximity, data quality, and impossible travel. Missing location is
neutral. IlliniCover does not continuously track location.

Exact location is never returned by public APIs or shown in public report
history. It is restricted to backend interpretation and specifically authorized
administrative abuse/debug review. Public history may retain only the venue,
reported value, time, and broad outside/inside context.

## Accounts, installations, billing, and network metadata

An installation receives a random credential so offline retries and independent
reports work without an account. Optional accounts store a verified email,
display name if supplied, linked installations, sessions, and a server-side
RevenueCat premium-entitlement mirror. The app stores raw installation and
session credentials only in the iOS Keychain on the device; the server stores
only keyed verifiers and the session linkage needed to authenticate them. A
pending email-authentication challenge uses a bearer credential kept in the
iOS Keychain. While the flow is pending, the server's database session stores
the email, account UUID when known, short-lived verification code, and bounded
attempt and resend state. The raw bearer credential is not stored server-side.
The code and pending server session become unusable after five minutes; the
nightly cleanup removes their expired database rows. Leaving the sign-in screen
or deleting the Keychain bearer does not itself send a remote cancellation, so
the bounded server row remains until that expiry. Challenge state is removed
sooner when the flow completes and all account- or email-bound challenge
sessions are removed when the account is deleted.

An unverified signup that is never authenticated and never gains a linked
installation, report association, billing/provider record, premium mirror,
audit reference, permission, or administrative role is treated as abandoned.
Nightly cleanup removes that account, email, and any remaining challenge state
after 24 hours. Accounts with any such durable dependency are preserved for
ordinary account-deletion handling instead.

The server derives a one-way keyed verifier from the client address for bounded
abuse correlation and rate limits; it does not retain the raw address in report
records. Network location is noisy and is not treated as proof that a person was
at a venue. The derived verifier is retained with private report context until
the account or guest installation is deleted or rotated.

Google Cloud Run automatically emits infrastructure request logs that can
include the requester address. IlliniCover configures the project log router to
exclude those request logs from storage, so they are not retained in the
project's Cloud Logging buckets. They are not copied into report records or used
as public evidence. This is separate from the keyed verifier above, which the
application creates for abuse controls without retaining the raw address.

IlliniCover's application logs use a deliberately minimal operational receipt,
and configured error monitoring uses the same fail-closed boundary: app or
server release, environment, generalized route, validated request ID when
available, exception type, and stack frame locations. Request and report
bodies, arbitrary log and exception messages, headers, cookies, query strings,
local variables, breadcrumbs, screenshots, user identity, performance traces,
and network traces are excluded before transmission or storage. External error
monitoring is disabled when its project key is not configured.

## Service providers and equivalent protection

IlliniCover uses narrowly scoped service providers only for the functions
described here: Google Cloud Run and Neon host the application and database;
RevenueCat processes purchase and entitlement state; and Sentry receives the
minimal error receipt described above only when monitoring is configured. These
providers do not receive report bodies or exact location unless that data is
required for the hosted backend to accept and assess the report. IlliniCover
configures access controls, transport security, logging, deletion, and
retention boundaries for each service and uses providers under terms that
require data protection. A provider integration remains disabled when its
required privacy and security configuration has not been completed.

IlliniCover does not sell personal data or allow these providers to use it for
cross-app tracking or advertising. Provider access is limited to operating,
securing, supporting, or billing for IlliniCover, and provider-held account
identifiers are deleted or deidentified through the account-deletion process
described below. If a provider cannot offer protection equivalent to the
commitments in this policy, IlliniCover will stop sending data to that provider
or stop offering the affected feature.

## Retention and deletion

Accepted observation values and provenance are durable evidence. They may be
retained after account deletion only after account, actor, exact location,
network verifier, session, entitlement, and provider metadata are removed so no
stable deleted-user pseudonym remains. Derived model releases and decisions are
reproducibility receipts, not official venue facts.

When exact location is supplied, it is retained with private report context
until the linked account is deleted or the guest installation is deleted or
rotated. This preservation supports later recalculation of distance, accuracy,
and impossible-travel rules; it is not continuous tracking. There is no
automatic shorter location-expiry period in the initial beta.

Deleting an account in the app immediately revokes local sessions and premium
access, removes profile and actor links, pending email challenges, and their
keyed session verifiers, erases private report context, deletes
stored RevenueCat webhook identifiers, and queues idempotent deletion of the
external RevenueCat customer record. Guest users can rotate/delete their local
installation actor, which erases that actor's private context while retaining
only deidentified evidence.

Operational session and rate-limit rows expire and are cleaned automatically.
Provider deletion work is retained only while pending; successful provider
deletion records are removed. Restricted audit records describe administrative
actions without storing report secrets.

Each successful installation-to-account link request retains its random request
UUID, completion time, and reference to the resulting link so a lost response
can be retried without redirecting the request to another installation. These
receipts are removed with the link when the installation is rotated or the
account is deleted; they have no independent post-link retention period.

To recover safely when an account-deletion response is lost, the app creates a
random deletion request UUID before sending the request. The server retains only
that UUID and completion/expiry timestamps for 30 days by default. This receipt
contains no account, email, installation, session, report, or billing linkage;
nightly cleanup removes it after the recovery window.

## Contact and choices

You can browse and report as a guest without providing an email or location.
Use account deletion for account-linked erasure, or installation rotation for
guest data erasure.

When support is configured and you choose **Report a Problem**, the app opens
your Mail app with a draft that you review before sending. The draft includes
the issue text you write, app and iOS versions, and any venue, approximate time,
decision ID, or request ID you choose to provide. IlliniCover does not attach
report payloads, location, email credentials, or authentication credentials.
The support mailbox and its email provider receive the message only after you
send it. Support correspondence is restricted to support and security work and
is retained only as long as needed to resolve and document the request, then
deleted under the mailbox retention process. You may ask support to delete a
request sooner, subject to any legal or security preservation requirement.

Before external beta, the support contact and public policy URL must be
configured in the app and App Store listing. App Store privacy answers must
match this policy and the app privacy manifest.
