class AccountActorMismatch(Exception):
    pass


def submission_account_id(actor, session_account):
    if session_account is not None:
        if actor.account_id not in {None, session_account.pk}:
            raise AccountActorMismatch
        return session_account.pk
    return actor.account_id
