import hmac
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from identity.credentials import (
    active_credential,
    installation_verifier,
    issue_installation,
)
from identity.models import (
    Account,
    AccountDeletionReceipt,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    InstallationActor,
    InstallationCredential,
    InstallationOperationReceipt,
    SessionTokenVerifier,
)
from identity.rate_limits import enforce_installation_issuance_limit


class InstallationAlreadyLinked(Exception):
    pass


class IdentityIdempotencyConflict(Exception):
    pass


class InvalidInstallationCredential(Exception):
    pass


def _lock_identity_value(value: str) -> None:
    """Serialize one idempotency key or verifier on production PostgreSQL."""

    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"identity:{value}"])


def _matching_installation_receipt(
    *, request_id, operation: str, raw_token: str
) -> InstallationOperationReceipt | None:
    receipt = (
        InstallationOperationReceipt.objects.select_related("actor").filter(pk=request_id).first()
    )
    if receipt is None:
        return None
    verifier = installation_verifier(raw_token)
    if receipt.operation != operation or not hmac.compare_digest(
        receipt.request_verifier, verifier
    ):
        raise IdentityIdempotencyConflict
    return receipt


@transaction.atomic
def create_installation(
    *, request_id, raw_token: str, remote_address: str | None
) -> InstallationOperationReceipt:
    verifier = installation_verifier(raw_token)
    _lock_identity_value(str(request_id))
    _lock_identity_value(verifier)
    existing = _matching_installation_receipt(
        request_id=request_id,
        operation=InstallationOperationReceipt.Operation.CREATE,
        raw_token=raw_token,
    )
    if existing is not None:
        return existing
    if InstallationCredential.objects.filter(verifier=verifier).exists():
        raise IdentityIdempotencyConflict
    enforce_installation_issuance_limit(
        remote_address=remote_address,
        now_seconds=int(timezone.now().timestamp()),
    )
    actor = issue_installation(raw_token)
    return InstallationOperationReceipt.objects.create(
        request_id=request_id,
        operation=InstallationOperationReceipt.Operation.CREATE,
        request_verifier=verifier,
        actor=actor,
    )


@transaction.atomic
def link_installation(account: Account, request_id, raw_token: str) -> ActorAccountLink | None:
    _lock_identity_value(str(request_id))
    # Whenever both identities participate, lock account before actor. Account
    # deletion uses the same order before taking its linked-actor snapshot.
    locked_account = (
        Account.objects.select_for_update().filter(pk=account.pk, is_active=True).first()
    )
    if locked_account is None:
        return None
    account = locked_account
    credential = active_credential(raw_token, for_update=True)
    if credential is None or not credential.matches(installation_verifier(raw_token)):
        return None
    actor = credential.actor
    # Equal request UUIDs serialize first. Equal actors with different request
    # UUIDs serialize second, so every accepted retry can persist its own
    # receipt without racing the actor's one-to-one link.
    _lock_identity_value(f"link-actor:{actor.id}")
    request_match = (
        ActorAccountLinkReceipt.objects.select_related("link").filter(pk=request_id).first()
    )
    if request_match is not None:
        if request_match.link.actor_id != actor.id or request_match.link.account_id != account.id:
            raise IdentityIdempotencyConflict
        if not request_match.link.is_attribution_active:
            ActorAccountLink.objects.filter(pk=request_match.link_id).update(
                is_attribution_active=True
            )
            request_match.link.is_attribution_active = True
        return request_match.link
    existing = ActorAccountLink.objects.select_for_update().filter(actor=actor).first()
    if existing:
        if existing.account_id != account.id:
            raise InstallationAlreadyLinked
        link = existing
        if not link.is_attribution_active:
            link.is_attribution_active = True
            link.save(update_fields=["is_attribution_active"])
    else:
        link = ActorAccountLink.objects.create(actor=actor, account=account)
    ActorAccountLinkReceipt.objects.create(request_id=request_id, link=link)
    return link


@transaction.atomic
def deactivate_installation_attribution(account: Account, raw_token: str | None) -> bool:
    """Disable attribution only for the authenticated account's own actor."""

    if not raw_token:
        return False
    locked_account = (
        Account.objects.select_for_update().filter(pk=account.pk, is_active=True).first()
    )
    if locked_account is None:
        return False
    account = locked_account
    credential = active_credential(raw_token, for_update=True)
    if credential is None or not credential.matches(installation_verifier(raw_token)):
        return False
    _lock_identity_value(f"link-actor:{credential.actor_id}")
    updated = ActorAccountLink.objects.filter(
        actor_id=credential.actor_id,
        account=account,
        is_attribution_active=True,
    ).update(is_attribution_active=False)
    return updated == 1


@transaction.atomic
def rotate_installation(
    *,
    request_id,
    replacement_token: str,
    presented_token: str | None,
    remote_address: str | None,
) -> InstallationOperationReceipt:
    replacement_verifier = installation_verifier(replacement_token)
    _lock_identity_value(str(request_id))
    _lock_identity_value(replacement_verifier)
    existing = _matching_installation_receipt(
        request_id=request_id,
        operation=InstallationOperationReceipt.Operation.ROTATE,
        raw_token=replacement_token,
    )
    if existing is not None:
        return existing
    # Receipt recovery is bound to the high-entropy replacement verifier, not
    # to possession of an arbitrary valid installation credential.
    if presented_token and hmac.compare_digest(
        installation_verifier(presented_token), replacement_verifier
    ):
        raise InvalidInstallationCredential
    if not presented_token:
        raise InvalidInstallationCredential
    candidate = active_credential(presented_token)
    if candidate is None or not candidate.matches(installation_verifier(presented_token)):
        raise InvalidInstallationCredential
    linked_account_id = (
        ActorAccountLink.objects.filter(actor_id=candidate.actor_id)
        .values_list("account_id", flat=True)
        .first()
    )
    if linked_account_id is not None:
        # Account deletion uses account -> actor/credential via cascades. Take
        # that same outer lifecycle lock before locking the credential.
        if not Account.objects.select_for_update().filter(pk=linked_account_id).exists():
            raise InvalidInstallationCredential
    credential = active_credential(presented_token, for_update=True)
    if credential is None or not credential.matches(installation_verifier(presented_token)):
        raise InvalidInstallationCredential
    actor = InstallationActor.objects.select_for_update().filter(pk=credential.actor_id).first()
    if actor is None:
        raise InvalidInstallationCredential
    current_linked_account_id = (
        ActorAccountLink.objects.filter(actor_id=actor.pk)
        .values_list("account_id", flat=True)
        .first()
    )
    if current_linked_account_id != linked_account_id:
        # The actor became linked while this rotation waited for its
        # credential. Retry so a linked rotation takes the account lifecycle
        # lock before it erases the actor and its durable privacy authority.
        raise InvalidInstallationCredential
    if InstallationCredential.objects.filter(verifier=replacement_verifier).exists():
        raise IdentityIdempotencyConflict
    enforce_installation_issuance_limit(
        remote_address=remote_address,
        now_seconds=int(timezone.now().timestamp()),
    )
    _delete_identity_rate_buckets(actor_ids=[actor.pk])
    _erase_actor_private_context(actor)
    actor.delete()
    replacement_actor = issue_installation(replacement_token)
    return InstallationOperationReceipt.objects.create(
        request_id=request_id,
        operation=InstallationOperationReceipt.Operation.ROTATE,
        request_verifier=replacement_verifier,
        actor=replacement_actor,
    )


def _erase_actor_private_context(actor: InstallationActor) -> None:
    from covers.models import CoverObservation
    from covers.privacy import erased_independence_group_key
    from submissions.models import Submission, SubmissionPrivateContext
    from submissions.services import erased_request_fingerprint

    # Collapse every erased contributor into the same venue/service-night
    # bucket. This preserves useful values without a stable deleted-installation
    # pseudonym and prevents report/rotate cycles from creating fake actors.
    for observation in (
        CoverObservation.objects.filter(submission__private_context__actor=actor)
        .select_related("submission")
        .iterator()
    ):
        CoverObservation.objects.filter(pk=observation.pk).update(
            independence_group_key=erased_independence_group_key(
                observation.submission.venue_id,
                observation.submission.observed_at_client,
            )
        )

    contexts = SubmissionPrivateContext.objects.filter(actor=actor)
    for submission_id in contexts.values_list("submission_id", flat=True).iterator():
        Submission.objects.filter(pk=submission_id).update(
            request_fingerprint=erased_request_fingerprint(submission_id)
        )
    contexts.update(
        actor=None,
        account=None,
        latitude=None,
        longitude=None,
        location_accuracy_m=None,
        network_verifier="",
        erased_at=timezone.now(),
    )


@transaction.atomic
def delete_account(account: Account, *, request_id) -> AccountDeletionReceipt:
    from billing.models import ProviderDeletionRequest, RevenueCatEvent
    from covers.models import CoverObservation
    from covers.privacy import erased_independence_group_key
    from django.contrib.sessions.models import Session
    from submissions.models import Submission, SubmissionPrivateContext
    from submissions.services import erased_request_fingerprint

    _lock_identity_value(str(request_id))
    account = Account.objects.select_for_update().get(pk=account.pk)
    if AccountDeletionReceipt.objects.filter(pk=request_id).exists():
        # A still-authenticated account cannot be the account whose completed
        # receipt is deliberately unlinkable. Treat an impossible UUID reuse
        # as a conflict instead of skipping somebody else's erasure.
        raise IdentityIdempotencyConflict
    account_reference = str(account.pk)
    ProviderDeletionRequest.objects.filter(
        provider_customer_id=account_reference,
        status=ProviderDeletionRequest.Status.SUCCEEDED,
    ).delete()
    ProviderDeletionRequest.objects.get_or_create(provider_customer_id=account_reference)
    provider_event_ids = []
    for event in RevenueCatEvent.objects.only("pk", "app_user_id", "payload").iterator(
        chunk_size=200
    ):
        if event.app_user_id == account_reference or _contains_exact_value(
            event.payload, account_reference
        ):
            provider_event_ids.append(event.pk)
    RevenueCatEvent.objects.filter(pk__in=provider_event_ids).delete()
    session_keys = _account_bound_session_keys(account)
    SessionTokenVerifier.objects.filter(
        Q(account=account) | Q(session_key__in=session_keys)
    ).delete()
    Session.objects.filter(session_key__in=session_keys).delete()
    linked_actor_ids = list(
        ActorAccountLink.objects.filter(account=account).values_list("actor_id", flat=True)
    )
    contexts = SubmissionPrivateContext.objects.filter(account=account)
    if linked_actor_ids:
        contexts = SubmissionPrivateContext.objects.filter(
            Q(account=account) | Q(actor_id__in=linked_actor_ids)
        )
    for observation in (
        CoverObservation.objects.filter(submission__private_context__in=contexts)
        .select_related("submission")
        .iterator()
    ):
        CoverObservation.objects.filter(pk=observation.pk).update(
            independence_group_key=erased_independence_group_key(
                observation.submission.venue_id,
                observation.submission.observed_at_client,
            )
        )
    for submission_id in contexts.values_list("submission_id", flat=True).iterator():
        Submission.objects.filter(pk=submission_id).update(
            request_fingerprint=erased_request_fingerprint(submission_id)
        )
    contexts.update(
        actor=None,
        account=None,
        latitude=None,
        longitude=None,
        location_accuracy_m=None,
        network_verifier="",
        erased_at=timezone.now(),
    )
    _delete_identity_rate_buckets(account_ids=[account.pk], actor_ids=linked_actor_ids)
    _scrub_account_audit_references(account_reference)
    # Contexts were erased above; deleting every linked actor also cascades its
    # verifier-only credential and issuance receipt. No deleted-user actor
    # pseudonym survives.
    InstallationActor.objects.filter(pk__in=linked_actor_ids).delete()
    account.delete()
    completed_at = timezone.now()
    return AccountDeletionReceipt.objects.create(
        request_id=request_id,
        completed_at=completed_at,
        expires_at=completed_at + timedelta(days=settings.ACCOUNT_DELETION_RECEIPT_RETENTION_DAYS),
    )


def _scrub_account_audit_references(account_reference: str) -> None:
    """Keep bounded audit facts without a deleted account's UUID or email."""

    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType
    from operations.models import AuditEvent

    AuditEvent.objects.filter(
        actor_kind="account",
        actor_reference=account_reference,
    ).update(actor_kind="deleted_account", actor_reference="")
    AuditEvent.objects.filter(target_reference=f"identity.account:{account_reference}").update(
        target_reference="identity.account:deleted"
    )

    account_content_type = ContentType.objects.get_for_model(Account)
    LogEntry.objects.filter(
        content_type=account_content_type,
        object_id=account_reference,
    ).update(object_id=None, object_repr="Deleted account")


def account_deletion_receipt(request_id) -> AccountDeletionReceipt | None:
    return AccountDeletionReceipt.objects.filter(
        pk=request_id,
        expires_at__gt=timezone.now(),
    ).first()


def _contains_exact_value(value, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, dict):
        return any(_contains_exact_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_value(item, expected) for item in value)
    return False


def _account_bound_session_keys(account: Account) -> list[str]:
    """Find auth and pending allauth code sessions bound to one account."""

    from django.contrib.auth import SESSION_KEY
    from django.contrib.sessions.models import Session

    account_reference = str(account.pk)
    normalized_email = account.email.strip().casefold()
    challenge_keys = ("account_login", "account_email_verification_code")
    session_keys = []
    for session in Session.objects.iterator():
        decoded = session.get_decoded()
        if str(decoded.get(SESSION_KEY, "")) == account_reference:
            session_keys.append(session.session_key)
            continue
        for challenge_key in challenge_keys:
            challenge = decoded.get(challenge_key)
            if challenge is None:
                continue
            if _contains_exact_value(challenge, account_reference) or _contains_normalized_email(
                challenge, normalized_email
            ):
                session_keys.append(session.session_key)
                break
    return session_keys


def _contains_normalized_email(value, expected: str) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() == expected
    if isinstance(value, dict):
        return any(_contains_normalized_email(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_normalized_email(item, expected) for item in value)
    return False


def _delete_identity_rate_buckets(*, account_ids=(), actor_ids=()) -> None:
    from submissions.models import SubmissionRateBucket

    prefixes = [
        *(f"report-rate:account:{account_id}:" for account_id in account_ids),
        *(f"report-rate:time-machine-account:{account_id}:" for account_id in account_ids),
        *(f"report-rate:actor:{actor_id}:" for actor_id in actor_ids),
    ]
    if not prefixes:
        return
    identity_buckets = Q()
    for prefix in prefixes:
        identity_buckets |= Q(pk__startswith=prefix)
    SubmissionRateBucket.objects.filter(identity_buckets).delete()


def cleanup_abandoned_unverified_accounts(*, now=None) -> int:
    """Delete never-authenticated, dependency-free signups after a bounded wait."""

    from allauth.account.models import EmailAddress

    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.ABANDONED_SIGNUP_RETENTION_SECONDS)
    candidates = list(
        Account.objects.filter(
            created_at__lte=cutoff,
            last_login__isnull=True,
            is_staff=False,
            is_superuser=False,
        )
        .exclude(emailaddress__verified=True)
        .values_list("pk", flat=True)
    )
    deleted = 0
    for account_id in candidates:
        with transaction.atomic():
            account = Account.objects.select_for_update().filter(pk=account_id).first()
            if account is None or account.last_login is not None:
                continue
            if (
                account.created_at > cutoff
                or EmailAddress.objects.filter(user=account, verified=True).exists()
            ):
                continue
            if _abandoned_account_has_dependencies(account):
                continue
            session_keys = _account_bound_session_keys(account)
            SessionTokenVerifier.objects.filter(
                Q(account=account) | Q(session_key__in=session_keys)
            ).delete()
            from django.contrib.sessions.models import Session

            Session.objects.filter(session_key__in=session_keys).delete()
            account.delete()
            deleted += 1
    return deleted


def _abandoned_account_has_dependencies(account: Account) -> bool:
    from billing.models import AccountEntitlement, ProviderDeletionRequest, RevenueCatEvent
    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType
    from operations.models import AuditEvent
    from submissions.models import SubmissionPrivateContext

    account_reference = str(account.pk)
    provider_event_reference = any(
        event.app_user_id == account_reference
        or _contains_exact_value(event.payload, account_reference)
        for event in RevenueCatEvent.objects.only("app_user_id", "payload").iterator(chunk_size=200)
    )
    account_content_type = ContentType.objects.get_for_model(Account)
    return any(
        (
            ActorAccountLink.objects.filter(account=account).exists(),
            SubmissionPrivateContext.objects.filter(account=account).exists(),
            AccountEntitlement.objects.filter(account=account).exists(),
            ProviderDeletionRequest.objects.filter(provider_customer_id=account_reference).exists(),
            provider_event_reference,
            AuditEvent.objects.filter(
                Q(actor_reference=account_reference)
                | Q(target_reference=f"identity.account:{account_reference}")
            ).exists(),
            LogEntry.objects.filter(
                content_type=account_content_type,
                object_id=account_reference,
            ).exists(),
            account.groups.exists(),
            account.user_permissions.exists(),
        )
    )
