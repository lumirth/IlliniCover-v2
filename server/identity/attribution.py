import uuid

from identity.models import Account, ActorAccountLink, InstallationActor


def submission_account_id(
    actor: InstallationActor,
    session_account: Account | None,
) -> uuid.UUID | None:
    """Return per-request account authority for one installation submission."""

    if session_account is None:
        return None
    return (
        ActorAccountLink.objects.filter(
            actor=actor,
            account=session_account,
            is_attribution_active=True,
        )
        .values_list("account_id", flat=True)
        .first()
    )
