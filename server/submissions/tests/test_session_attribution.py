import uuid

import pytest
from covers.services import service_date_for
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone
from identity.models import Account, ActorAccountLink, InstallationActor
from identity.tokens import issue_session_token
from venues.models import Venue

from submissions.models import SubmissionPrivateContext, SubmissionRateBucket


def _linked_installation(client: Client, account: Account) -> str:
    raw_token = "ic_install_" + uuid.uuid4().hex + uuid.uuid4().hex
    issued = client.post(
        "/api/v2/installations",
        data={"requestId": str(uuid.uuid4()), "installationToken": raw_token},
        content_type="application/json",
    )
    assert issued.status_code == 201
    ActorAccountLink.objects.create(
        actor=InstallationActor.objects.get(pk=issued.json()["actorId"]),
        account=account,
    )
    return issued.json()["token"]


def _session_token(account: Account, *, expired: bool = False) -> str:
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    token = issue_session_token(session)
    if expired:
        Session.objects.filter(session_key=session.session_key).update(
            expire_date=timezone.now()
        )
    return token


def _submit(
    client: Client,
    *,
    kind: str,
    venue: Venue,
    installation_token: str,
    session_token: str | None,
) -> tuple[object, SubmissionPrivateContext]:
    observed_at = timezone.now()
    submission_id = uuid.uuid4()
    if kind == "cover":
        endpoint = "/api/v2/cover-submissions"
        payload = {
            "submissionId": str(submission_id),
            "venueId": str(venue.pk),
            "observedAt": observed_at.isoformat(),
            "cover": {"priceCents": 2_000, "interaction": "manual"},
        }
    else:
        endpoint = "/api/v2/deal-evidence"
        payload = {
            "submissionId": str(submission_id),
            "venueId": str(venue.pk),
            "observedAt": observed_at.isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": service_date_for(observed_at).isoformat(),
            "submittedDealShape": {
                "displayName": "$3 wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 300,
            },
        }
    headers = {"X-Installation-Token": installation_token}
    if session_token is not None:
        headers["X-Session-Token"] = session_token
    response = client.post(
        endpoint,
        data=payload,
        content_type="application/json",
        headers=headers,
    )
    return response, SubmissionPrivateContext.objects.get(submission_id=submission_id)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_submission_attributes_matching_active_account_session(kind):
    client = Client()
    venue = Venue.objects.create(slug=f"matching-{kind}", name=f"Matching {kind}")
    account = Account.objects.create_user(f"matching-{kind}@example.com")
    installation_token = _linked_installation(client, account)

    response, context = _submit(
        client,
        kind=kind,
        venue=venue,
        installation_token=installation_token,
        session_token=_session_token(account),
    )

    assert response.status_code == 201
    assert context.account_id == account.pk
    assert SubmissionRateBucket.objects.filter(
        pk__startswith=f"report-rate:account:{account.pk}:"
    ).exists()
    if kind == "cover":
        assert context.evidence_snapshot["signedIn"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_submission_without_session_is_guest_even_with_active_durable_link(kind):
    client = Client()
    venue = Venue.objects.create(slug=f"absent-{kind}", name=f"Absent {kind}")
    account = Account.objects.create_user(f"absent-{kind}@example.com")
    installation_token = _linked_installation(client, account)

    response, context = _submit(
        client,
        kind=kind,
        venue=venue,
        installation_token=installation_token,
        session_token=None,
    )

    assert response.status_code == 201
    assert context.account_id is None
    assert not SubmissionRateBucket.objects.filter(
        pk__startswith=f"report-rate:account:{account.pk}:"
    ).exists()
    if kind == "cover":
        assert context.evidence_snapshot["signedIn"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_submission_with_expired_session_is_guest(kind):
    client = Client()
    venue = Venue.objects.create(slug=f"expired-{kind}", name=f"Expired {kind}")
    account = Account.objects.create_user(f"expired-{kind}@example.com")
    installation_token = _linked_installation(client, account)

    response, context = _submit(
        client,
        kind=kind,
        venue=venue,
        installation_token=installation_token,
        session_token=_session_token(account, expired=True),
    )

    assert response.status_code == 201
    assert context.account_id is None
    assert not SubmissionRateBucket.objects.filter(
        pk__startswith=f"report-rate:account:{account.pk}:"
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_submission_with_mismatched_session_fails_closed_to_guest(kind):
    client = Client()
    venue = Venue.objects.create(slug=f"mismatch-{kind}", name=f"Mismatch {kind}")
    linked_account = Account.objects.create_user(f"linked-{kind}@example.com")
    other_account = Account.objects.create_user(f"other-{kind}@example.com")
    installation_token = _linked_installation(client, linked_account)

    response, context = _submit(
        client,
        kind=kind,
        venue=venue,
        installation_token=installation_token,
        session_token=_session_token(other_account),
    )

    assert response.status_code == 201
    assert context.account_id is None
    assert not SubmissionRateBucket.objects.filter(
        pk__startswith="report-rate:account:"
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_matching_session_does_not_override_inactive_attribution_link(kind):
    client = Client()
    venue = Venue.objects.create(slug=f"inactive-{kind}", name=f"Inactive {kind}")
    account = Account.objects.create_user(f"inactive-{kind}@example.com")
    installation_token = _linked_installation(client, account)
    ActorAccountLink.objects.update(is_attribution_active=False)

    response, context = _submit(
        client,
        kind=kind,
        venue=venue,
        installation_token=installation_token,
        session_token=_session_token(account),
    )

    assert response.status_code == 201
    assert context.account_id is None
