import uuid

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.utils import timezone
from submissions.models import SubmissionPrivateContext
from venues.models import Venue

from identity.models import Account, ActorAccountLink, InstallationActor
from identity.tokens import issue_session_token


def _session_token(account: Account) -> str:
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session[BACKEND_SESSION_KEY] = "allauth.account.auth_backends.AuthenticationBackend"
    session[HASH_SESSION_KEY] = account.get_session_auth_hash()
    session.save()
    return issue_session_token(session)


def _installation(client: Client, character: str = "a") -> dict:
    response = client.post(
        "/api/v2/installations",
        data={
            "requestId": str(uuid.uuid4()),
            "installationToken": "ic_install_" + character * 43,
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    return response.json()


def _link(
    client: Client,
    *,
    session_token: str,
    installation_token: str,
    request_id: uuid.UUID,
):
    return client.post(
        "/api/v2/me/link-installation",
        data={
            "requestId": str(request_id),
            "installationToken": installation_token,
        },
        content_type="application/json",
        headers={"X-Session-Token": session_token},
    )


def _submit_cover(
    client: Client,
    venue: Venue,
    installation_token: str,
    *,
    session_token: str | None = None,
):
    headers = {"X-Installation-Token": installation_token}
    if session_token is not None:
        headers["X-Session-Token"] = session_token
    response = client.post(
        "/api/v2/cover-submissions",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "cover": {"priceCents": 2_000, "interaction": "manual"},
        },
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 201
    return SubmissionPrivateContext.objects.get(submission_id=response.json()["submissionId"])


@pytest.mark.django_db
def test_logout_deactivates_account_attribution_and_same_link_retry_reactivates_it():
    client = Client()
    venue = Venue.objects.create(slug="logout", name="Logout")
    account = Account.objects.create_user("owner@example.com")
    installation = _installation(client)
    request_id = uuid.uuid4()
    first_session_token = _session_token(account)

    linked = _link(
        client,
        session_token=first_session_token,
        installation_token=installation["token"],
        request_id=request_id,
    )
    signed_in_context = _submit_cover(
        client,
        venue,
        installation["token"],
        session_token=first_session_token,
    )

    logged_out = client.delete(
        "/_allauth/app/v1/auth/session",
        headers={
            "X-Session-Token": first_session_token,
            "X-Installation-Token": installation["token"],
        },
    )

    assert linked.status_code == 200
    assert signed_in_context.account_id == account.id
    assert signed_in_context.evidence_snapshot["signedIn"] is True
    assert logged_out.status_code == 401
    link = ActorAccountLink.objects.get(actor_id=installation["actorId"])
    assert link.account_id == account.id
    assert link.is_attribution_active is False

    signed_out_context = _submit_cover(client, venue, installation["token"])
    assert signed_out_context.account_id is None
    assert signed_out_context.evidence_snapshot["signedIn"] is False

    reactivated_session_token = _session_token(account)
    relinked = _link(
        client,
        session_token=reactivated_session_token,
        installation_token=installation["token"],
        request_id=request_id,
    )
    assert relinked.status_code == 200
    link.refresh_from_db()
    assert link.is_attribution_active is True

    reactivated_context = _submit_cover(
        client,
        venue,
        installation["token"],
        session_token=reactivated_session_token,
    )
    assert reactivated_context.account_id == account.id
    assert reactivated_context.evidence_snapshot["signedIn"] is True


@pytest.mark.django_db
def test_logout_cannot_deactivate_an_installation_linked_to_another_account():
    client = Client()
    owner = Account.objects.create_user("owner@example.com")
    other = Account.objects.create_user("other@example.com")
    installation = _installation(client)
    link_request_id = uuid.uuid4()
    linked = _link(
        client,
        session_token=_session_token(owner),
        installation_token=installation["token"],
        request_id=link_request_id,
    )

    logged_out = client.delete(
        "/_allauth/app/v1/auth/session",
        headers={
            "X-Session-Token": _session_token(other),
            "X-Installation-Token": installation["token"],
        },
    )

    assert linked.status_code == 200
    assert logged_out.status_code == 401
    link = ActorAccountLink.objects.get(actor_id=installation["actorId"])
    assert link.account_id == owner.id
    assert link.is_attribution_active is True


@pytest.mark.django_db
def test_account_deletion_erases_actor_context_created_while_link_was_inactive():
    client = Client()
    venue = Venue.objects.create(slug="signed-out", name="Signed Out")
    account = Account.objects.create_user("delete@example.com")
    installation = _installation(client)
    session_token = _session_token(account)
    linked = _link(
        client,
        session_token=session_token,
        installation_token=installation["token"],
        request_id=uuid.uuid4(),
    )
    assert linked.status_code == 200

    logged_out = client.delete(
        "/_allauth/app/v1/auth/session",
        headers={
            "X-Session-Token": session_token,
            "X-Installation-Token": installation["token"],
        },
    )
    assert logged_out.status_code == 401
    context = _submit_cover(client, venue, installation["token"])
    assert context.account_id is None
    assert context.actor_id == uuid.UUID(installation["actorId"])

    deleted = client.delete(
        "/api/v2/me",
        data={"requestId": str(uuid.uuid4())},
        content_type="application/json",
        headers={"X-Session-Token": _session_token(account)},
    )

    assert deleted.status_code == 200
    context.refresh_from_db()
    assert context.actor_id is None
    assert context.account_id is None
    assert context.erased_at is not None
    assert not InstallationActor.objects.filter(pk=installation["actorId"]).exists()
