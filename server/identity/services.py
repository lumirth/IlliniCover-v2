from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from product.models import Account, InstallationActor

from identity.credentials import installation_verifier, lookup_installation
from identity.rate_limits import enforce_installation_issuance_limit, forget


class IdentityIdempotencyConflict(Exception):
    pass


class InstallationAlreadyLinked(Exception):
    pass


class InvalidInstallationCredential(Exception):
    pass


@transaction.atomic
def create_installation(raw_token: str, remote_address: str | None):
    enforce_installation_issuance_limit(remote_address, now_seconds=int(timezone.now().timestamp()))
    try:
        actor = InstallationActor.objects.create(verifier=installation_verifier(raw_token))
    except IntegrityError as error:
        raise IdentityIdempotencyConflict from error
    return actor


@transaction.atomic
def link_installation(account: Account, raw_token: str):
    # Account -> installation is the identity lock order shared with submissions
    # and deletion. Reversing it can deadlock an account deletion against a link.
    account = Account.objects.select_for_update().get(pk=account.pk)
    actor = lookup_installation(raw_token, for_update=True)
    if actor is None:
        return None
    if actor.account_id not in {None, account.pk}:
        raise InstallationAlreadyLinked
    actor.account = account
    actor.save(update_fields=["account"])
    return actor


def _erase_context(*, actor_ids=(), account_id=None) -> None:
    from product.models import Submission, SubmissionPrivateContext

    private = SubmissionPrivateContext.objects.filter(
        Q(actor_id__in=actor_ids) | Q(account_id=account_id)
        if account_id
        else Q(actor_id__in=actor_ids)
    )
    observed = private.values("submission_id")
    groups = [*actor_ids, *([account_id] if account_id else [])]
    Submission.objects.filter(Q(pk__in=observed) | Q(independence_group__in=groups)).update(
        independence_group=None
    )
    private.delete()
    for actor_id in actor_ids:
        forget(f"report:actor:{actor_id}")


@transaction.atomic
def rotate_installation(
    replacement_token: str, presented_token: str | None, remote_address: str | None
):
    if not presented_token:
        raise InvalidInstallationCredential
    enforce_installation_issuance_limit(remote_address, now_seconds=int(timezone.now().timestamp()))
    old = lookup_installation(presented_token, for_update=True)
    if old is None:
        raise InvalidInstallationCredential
    try:
        new = InstallationActor.objects.create(
            verifier=installation_verifier(replacement_token),
        )
    except IntegrityError as error:
        raise IdentityIdempotencyConflict from error
    _erase_context(actor_ids=[old.pk])
    old.delete()
    return new


@transaction.atomic
def delete_account(account: Account):
    from product.models import ProviderDeletionRequest

    account = Account.objects.select_for_update().get(pk=account.pk)
    actor_ids = list(
        InstallationActor.objects.select_for_update()
        .filter(account=account)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    _erase_context(actor_ids=actor_ids, account_id=account.pk)
    forget(f"report:account:{account.pk}")
    forget(f"time-machine-account:{account.pk}")
    Session.objects.filter(
        session_key__in=account.session_token_verifiers.values("session_key")
    ).delete()
    deletion, _ = ProviderDeletionRequest.objects.get_or_create(
        provider_customer_id=str(account.pk)
    )
    from billing.revenuecat import process_deletion

    transaction.on_commit(lambda: process_deletion(deletion))
    account.delete()
