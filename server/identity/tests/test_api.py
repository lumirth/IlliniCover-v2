import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, override_settings
from django.utils import timezone
from submissions.models import SubmissionRateBucket

from identity.models import (
    Account,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    IdentityRateBucket,
    InstallationActor,
    InstallationCredential,
    InstallationOperationReceipt,
)
from identity.tokens import issue_session_token


def token(character: str) -> str:
    return "ic_install_" + character * 43


def create_payload(*, request_id=None, raw_token=None):
    return {
        "requestId": str(request_id or uuid.uuid4()),
        "installationToken": raw_token or token("a"),
    }


@pytest.mark.django_db
def test_installation_endpoint_is_client_keyed_verifier_only_and_sequentially_idempotent():
    request_id = uuid.uuid4()
    payload = create_payload(request_id=request_id, raw_token=token("a"))
    client = Client()

    first = client.post(
        "/api/v2/installations",
        data=payload,
        content_type="application/json",
    )
    duplicate = client.post(
        "/api/v2/installations",
        data=payload,
        content_type="application/json",
    )

    assert first.status_code == duplicate.status_code == 201
    assert first.headers["Cache-Control"] == duplicate.headers["Cache-Control"] == "no-store"
    assert first.json() == duplicate.json()
    assert first.json()["requestId"] == str(request_id)
    assert first.json()["token"] == token("a")
    assert token("a") not in InstallationCredential.objects.get().verifier
    assert InstallationActor.objects.count() == 1
    assert InstallationOperationReceipt.objects.count() == 1
    assert IdentityRateBucket.objects.get().count == 1


@pytest.mark.django_db
def test_current_installation_is_a_side_effect_free_credential_probe():
    client = Client()
    created = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("a")),
        content_type="application/json",
    )
    actor_id = created.json()["actorId"]
    before = {
        "actors": InstallationActor.objects.count(),
        "credentials": InstallationCredential.objects.count(),
        "receipts": InstallationOperationReceipt.objects.count(),
        "rateBuckets": IdentityRateBucket.objects.count(),
        "actorLastSeenAt": InstallationActor.objects.get().last_seen_at,
        "credentialLastUsedAt": InstallationCredential.objects.get().last_used_at,
    }

    current = client.get(
        "/api/v2/installations/current",
        headers={"X-Installation-Token": token("a")},
    )
    revoked = client.get(
        "/api/v2/installations/current",
        headers={"X-Installation-Token": token("b")},
    )

    assert current.status_code == 200
    assert current.headers["Cache-Control"] == "no-store"
    assert current.json() == {"actorId": actor_id}
    assert revoked.status_code == 401
    assert revoked.headers["Cache-Control"] == "no-store"
    assert {
        "actors": InstallationActor.objects.count(),
        "credentials": InstallationCredential.objects.count(),
        "receipts": InstallationOperationReceipt.objects.count(),
        "rateBuckets": IdentityRateBucket.objects.count(),
        "actorLastSeenAt": InstallationActor.objects.get().last_seen_at,
        "credentialLastUsedAt": InstallationCredential.objects.get().last_used_at,
    } == before


@pytest.mark.django_db
def test_installation_request_uuid_and_token_reuse_conflicts_fail_closed():
    client = Client()
    request_id = uuid.uuid4()
    first = client.post(
        "/api/v2/installations",
        data=create_payload(request_id=request_id, raw_token=token("a")),
        content_type="application/json",
    )
    changed_payload = client.post(
        "/api/v2/installations",
        data=create_payload(request_id=request_id, raw_token=token("b")),
        content_type="application/json",
    )
    changed_request = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("a")),
        content_type="application/json",
    )

    assert first.status_code == 201
    assert changed_payload.status_code == changed_request.status_code == 409
    assert changed_payload.json()["code"] == "idempotency_conflict"
    assert InstallationActor.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {
            "requestId": str(uuid.UUID(int=0)),
            "installationToken": "ic_install_" + "a" * 43,
        },
        {
            "requestId": str(uuid.uuid4()),
            "installationToken": "ic_install_predictable",
        },
    ],
)
def test_installation_issuance_rejects_nonrandom_request_ids_and_short_tokens(payload):
    response = Client().post(
        "/api/v2/installations",
        data=payload,
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert InstallationActor.objects.count() == 0


@pytest.mark.django_db
@override_settings(INSTALLATION_ISSUANCE_RATE_LIMIT=(2, 3600))
def test_installation_creation_and_rotation_share_a_durable_network_issuance_limit():
    client = Client()
    created = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("a")),
        content_type="application/json",
        REMOTE_ADDR="203.0.113.11",
    )
    rotated = client.post(
        "/api/v2/installations/rotate",
        data={
            "requestId": str(uuid.uuid4()),
            "replacementInstallationToken": token("b"),
        },
        content_type="application/json",
        headers={"X-Installation-Token": token("a")},
        REMOTE_ADDR="203.0.113.11",
    )
    limited = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("c")),
        content_type="application/json",
        REMOTE_ADDR="203.0.113.11",
    )

    assert created.status_code == rotated.status_code == 201
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert InstallationActor.objects.count() == 1
    assert IdentityRateBucket.objects.get().count == 2


@pytest.mark.django_db
def test_rotation_retry_succeeds_with_replacement_token_after_old_actor_was_erased():
    client = Client()
    created = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("a")),
        content_type="application/json",
    ).json()
    old_actor_id = created["actorId"]
    account = Account.objects.create_user("rotated-link@example.com")
    link = ActorAccountLink.objects.create(actor_id=old_actor_id, account=account)
    link_request_id = uuid.uuid4()
    ActorAccountLinkReceipt.objects.create(request_id=link_request_id, link=link)
    actor_rate_key = f"report-rate:actor:{old_actor_id}:1"
    network_rate_key = "report-rate:network:unrelated-verifier:1"
    SubmissionRateBucket.objects.bulk_create(
        [
            SubmissionRateBucket(
                key=key,
                count=1,
                expires_at=timezone.now() + timedelta(hours=1),
            )
            for key in (actor_rate_key, network_rate_key)
        ]
    )
    request_id = uuid.uuid4()
    payload = {
        "requestId": str(request_id),
        "replacementInstallationToken": token("b"),
    }

    first = client.post(
        "/api/v2/installations/rotate",
        data=payload,
        content_type="application/json",
        headers={"X-Installation-Token": token("a")},
    )
    duplicate_without_old_token = client.post(
        "/api/v2/installations/rotate",
        data=payload,
        content_type="application/json",
        headers={"X-Installation-Token": token("b")},
    )

    assert first.status_code == duplicate_without_old_token.status_code == 201
    assert first.headers["Cache-Control"] == "no-store"
    assert duplicate_without_old_token.headers["Cache-Control"] == "no-store"
    assert first.json() == duplicate_without_old_token.json()
    assert first.json()["actorId"] != old_actor_id
    assert not InstallationActor.objects.filter(pk=old_actor_id).exists()
    assert InstallationActor.objects.count() == InstallationCredential.objects.count() == 1
    assert InstallationOperationReceipt.objects.count() == 1
    assert not ActorAccountLinkReceipt.objects.filter(pk=link_request_id).exists()
    assert not SubmissionRateBucket.objects.filter(pk=actor_rate_key).exists()
    assert SubmissionRateBucket.objects.filter(pk=network_rate_key).exists()
    assert Account.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_replacement_token_cannot_authorize_a_rotation_that_has_no_completed_receipt():
    client = Client()
    response = client.post(
        "/api/v2/installations/rotate",
        data={
            "requestId": str(uuid.uuid4()),
            "replacementInstallationToken": token("b"),
        },
        content_type="application/json",
        headers={"X-Installation-Token": token("b")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_installation_token"
    assert not InstallationActor.objects.exists()


@pytest.mark.django_db
def test_account_session_can_idempotently_link_an_installation_with_request_uuid():
    account = Account.objects.create_user("person@example.com")
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    session_token = issue_session_token(session)
    created = (
        Client()
        .post(
            "/api/v2/installations",
            data=create_payload(raw_token=token("a")),
            content_type="application/json",
        )
        .json()
    )
    request_id = uuid.uuid4()
    payload = {
        "requestId": str(request_id),
        "installationToken": created["token"],
    }
    client = Client()

    first = client.post(
        "/api/v2/me/link-installation",
        data=payload,
        content_type="application/json",
        headers={"X-Session-Token": session_token},
    )
    duplicate = client.post(
        "/api/v2/me/link-installation",
        data=payload,
        content_type="application/json",
        headers={"X-Session-Token": session_token},
    )

    expected = {
        "requestId": str(request_id),
        "actorId": created["actorId"],
        "accountId": str(account.id),
    }
    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json() == expected
    link = ActorAccountLink.objects.get()
    assert ActorAccountLinkReceipt.objects.get(pk=request_id).link == link


@pytest.mark.django_db
def test_fresh_link_request_uuid_for_same_account_is_durably_reserved():
    account = Account.objects.create_user("same-account@example.com")
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    session_token = issue_session_token(session)
    created = (
        Client()
        .post(
            "/api/v2/installations",
            data=create_payload(raw_token=token("a")),
            content_type="application/json",
        )
        .json()
    )
    client = Client()
    request_ids = (uuid.uuid4(), uuid.uuid4())

    responses = [
        client.post(
            "/api/v2/me/link-installation",
            data={
                "requestId": str(request_id),
                "installationToken": created["token"],
            },
            content_type="application/json",
            headers={"X-Session-Token": session_token},
        )
        for request_id in request_ids
    ]

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.json()["requestId"] for response in responses] == [
        str(request_id) for request_id in request_ids
    ]
    link = ActorAccountLink.objects.get()
    assert set(ActorAccountLinkReceipt.objects.values_list("request_id", flat=True)) == set(
        request_ids
    )
    assert set(ActorAccountLinkReceipt.objects.values_list("link_id", flat=True)) == {link.pk}


@pytest.mark.django_db
def test_accepted_fresh_link_request_uuid_cannot_later_target_another_actor():
    account = Account.objects.create_user("request-owner@example.com")
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    session_token = issue_session_token(session)
    client = Client()
    first_actor = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("a")),
        content_type="application/json",
    ).json()
    second_actor = client.post(
        "/api/v2/installations",
        data=create_payload(raw_token=token("b")),
        content_type="application/json",
        REMOTE_ADDR="203.0.113.12",
    ).json()
    initial_request_id = uuid.uuid4()
    accepted_request_id = uuid.uuid4()

    for request_id in (initial_request_id, accepted_request_id):
        response = client.post(
            "/api/v2/me/link-installation",
            data={
                "requestId": str(request_id),
                "installationToken": first_actor["token"],
            },
            content_type="application/json",
            headers={"X-Session-Token": session_token},
        )
        assert response.status_code == 200

    redirected = client.post(
        "/api/v2/me/link-installation",
        data={
            "requestId": str(accepted_request_id),
            "installationToken": second_actor["token"],
        },
        content_type="application/json",
        headers={"X-Session-Token": session_token},
    )

    assert redirected.status_code == 409
    assert redirected.json()["code"] == "idempotency_conflict"
    receipt = ActorAccountLinkReceipt.objects.select_related("link").get(pk=accepted_request_id)
    assert str(receipt.link.actor_id) == first_actor["actorId"]
    assert not ActorAccountLink.objects.filter(actor_id=second_actor["actorId"]).exists()
