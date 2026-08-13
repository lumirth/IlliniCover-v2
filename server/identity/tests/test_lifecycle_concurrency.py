import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from allauth.account.models import EmailAddress
from covers.models import CoverObservation
from covers.privacy import erased_independence_group_key
from covers.services import service_date_for
from deals.models import DealEvidenceEvent
from deals.schemas import DealEvidenceInputSchema
from deals.services import accept_deal_evidence
from django.contrib.sessions.models import Session
from django.db import connection, connections
from django.test import Client
from django.utils import timezone
from submissions.models import SubmissionPrivateContext
from submissions.schemas import CoverSubmissionSchema
from submissions.services import accept_cover_submission
from venues.models import Venue

from identity.credentials import issue_installation
from identity.headless_views import LifecycleRequestLoginCodeView
from identity.models import (
    Account,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    InstallationActor,
    SessionTokenVerifier,
)
from identity.services import (
    InvalidInstallationCredential,
    delete_account,
    link_installation,
    rotate_installation,
)


def _postgres_only():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance test")


def _close_connections(worker):
    def wrapped(*args, **kwargs):
        connections.close_all()
        try:
            return worker(*args, **kwargs)
        finally:
            connections.close_all()

    return wrapped


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["cover", "deal"])
def test_submission_that_wins_actor_lock_is_still_erased_by_concurrent_account_deletion(kind):
    _postgres_only()
    venue = Venue.objects.create(slug=f"race-{kind}", name=f"Race {kind}")
    account = Account.objects.create_user(f"race-{kind}@example.com")
    actor = issue_installation("ic_install_" + "a" * 43)
    ActorAccountLink.objects.create(actor=actor, account=account)
    now = timezone.now()
    submission_id = uuid.uuid4()
    if kind == "cover":
        payload = CoverSubmissionSchema.model_validate(
            {
                "submissionId": str(submission_id),
                "venueId": str(venue.id),
                "observedAt": now.isoformat(),
                "location": {
                    "latitude": 40.11,
                    "longitude": -88.23,
                    "accuracyMeters": 5,
                },
                "cover": {"priceCents": 2_000, "interaction": "manual"},
            }
        )
        submit = accept_cover_submission
        limit_patch = "submissions.services.enforce_submission_limits"
    else:
        payload = DealEvidenceInputSchema.model_validate(
            {
                "submissionId": str(submission_id),
                "venueId": str(venue.id),
                "observedAt": now.isoformat(),
                "action": "ADD_MISSING",
                "serviceDateLocal": service_date_for(now).isoformat(),
                "location": {
                    "latitude": 40.11,
                    "longitude": -88.23,
                    "accuracyMeters": 5,
                },
                "submittedDealShape": {
                    "displayName": "$3 wells",
                    "category": "drink",
                    "priceKind": "single",
                    "priceCents": 300,
                },
            }
        )
        submit = accept_deal_evidence
        limit_patch = "deals.services.enforce_submission_limits"

    actor_locked = threading.Event()
    release_submission = threading.Event()
    deletion_started = threading.Event()

    def paused_limits(*_args, **_kwargs):
        actor_locked.set()
        assert release_submission.wait(timeout=10)

    @_close_connections
    def submit_worker():
        return submit(
            InstallationActor.objects.get(pk=actor.pk),
            payload,
            remote_address="203.0.113.90",
        )

    @_close_connections
    def delete_worker():
        deletion_started.set()
        return delete_account(
            Account.objects.get(pk=account.pk),
            request_id=uuid.uuid4(),
        )

    with (
        patch(limit_patch, side_effect=paused_limits),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        submitted = executor.submit(submit_worker)
        assert actor_locked.wait(timeout=10)
        deleted = executor.submit(delete_worker)
        assert deletion_started.wait(timeout=10)
        assert not deleted.done()
        release_submission.set()
        submitted.result(timeout=10)
        deleted.result(timeout=10)

    context = SubmissionPrivateContext.objects.get(submission_id=submission_id)
    assert context.actor_id is None
    assert context.account_id is None
    assert context.latitude is None
    assert context.longitude is None
    assert context.network_verifier == ""
    assert context.erased_at is not None
    assert not InstallationActor.objects.filter(pk=actor.pk).exists()
    if kind == "cover":
        observation = CoverObservation.objects.get(submission_id=submission_id)
        assert observation.independence_group_key == erased_independence_group_key(
            venue.id, now
        )
    else:
        assert DealEvidenceEvent.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db(transaction=True)
def test_link_cannot_commit_after_account_deletion_takes_its_lifecycle_lock():
    _postgres_only()
    account = Account.objects.create_user("link-delete-race@example.com")
    raw_token = "ic_install_" + "b" * 43
    actor = issue_installation(raw_token)
    deletion_holds_account = threading.Event()
    release_deletion = threading.Event()
    link_reached_actor = threading.Event()

    from identity.services import _account_bound_session_keys

    def paused_session_scan(locked_account):
        deletion_holds_account.set()
        assert release_deletion.wait(timeout=10)
        return _account_bound_session_keys(locked_account)

    from identity.services import active_credential as real_active_credential

    def observed_active_credential(*args, **kwargs):
        link_reached_actor.set()
        return real_active_credential(*args, **kwargs)

    @_close_connections
    def delete_worker():
        return delete_account(Account.objects.get(pk=account.pk), request_id=uuid.uuid4())

    @_close_connections
    def link_worker():
        return link_installation(
            Account.objects.get(pk=account.pk),
            uuid.uuid4(),
            raw_token,
        )

    with (
        patch(
            "identity.services._account_bound_session_keys",
            side_effect=paused_session_scan,
        ),
        patch("identity.services.active_credential", side_effect=observed_active_credential),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        deleted = executor.submit(delete_worker)
        assert deletion_holds_account.wait(timeout=10)
        linked = executor.submit(link_worker)
        assert not link_reached_actor.wait(timeout=0.2)
        release_deletion.set()
        deleted.result(timeout=10)
        assert linked.result(timeout=10) is None

    assert not ActorAccountLink.objects.filter(actor=actor).exists()
    assert InstallationActor.objects.filter(pk=actor.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_login_challenge_cannot_persist_after_account_deletion_session_scan():
    _postgres_only()
    account = Account.objects.create_user("challenge-delete-race@example.com")
    EmailAddress.objects.create(
        user=account,
        email=account.email,
        verified=True,
        primary=True,
    )
    deletion_holds_account = threading.Event()
    release_deletion = threading.Event()
    request_reached_lock = threading.Event()

    from identity.services import _account_bound_session_keys

    def paused_session_scan(locked_account):
        deletion_holds_account.set()
        assert release_deletion.wait(timeout=10)
        return _account_bound_session_keys(locked_account)

    real_post = LifecycleRequestLoginCodeView.post

    def observed_post(view, request, *args, **kwargs):
        request_reached_lock.set()
        return real_post(view, request, *args, **kwargs)

    @_close_connections
    def delete_worker():
        return delete_account(Account.objects.get(pk=account.pk), request_id=uuid.uuid4())

    @_close_connections
    def challenge_worker():
        return Client().post(
            "/_allauth/app/v1/auth/code/request",
            data={"email": account.email},
            content_type="application/json",
        )

    with (
        patch(
            "identity.services._account_bound_session_keys",
            side_effect=paused_session_scan,
        ),
        patch.object(LifecycleRequestLoginCodeView, "post", new=observed_post),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        deleted = executor.submit(delete_worker)
        assert deletion_holds_account.wait(timeout=10)
        challenged = executor.submit(challenge_worker)
        assert request_reached_lock.wait(timeout=10)
        release_deletion.set()
        deleted.result(timeout=10)
        response = challenged.result(timeout=10)

    assert response.status_code == 401
    assert "session_token" not in response.json().get("meta", {})
    assert not Account.objects.filter(pk=account.pk).exists()
    assert not Session.objects.exists()
    assert not SessionTokenVerifier.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_rotation_rejects_actor_that_became_linked_while_waiting_for_credential_lock():
    _postgres_only()
    account = Account.objects.create_user("link-rotate-race@example.com")
    raw_token = "ic_install_" + "c" * 43
    replacement_token = "ic_install_" + "d" * 43
    actor = issue_installation(raw_token)
    link_created = threading.Event()
    release_link = threading.Event()
    rotation_reached_credential_lock = threading.Event()
    rotation_thread_id: list[int] = []
    real_create = ActorAccountLinkReceipt.objects.create
    from identity.services import active_credential as real_active_credential

    def paused_receipt_create(*args, **kwargs):
        receipt = real_create(*args, **kwargs)
        link_created.set()
        assert release_link.wait(timeout=10)
        return receipt

    @_close_connections
    def link_worker():
        return link_installation(account, uuid.uuid4(), raw_token)

    @_close_connections
    def rotate_worker():
        rotation_thread_id.append(threading.get_ident())
        return rotate_installation(
            request_id=uuid.uuid4(),
            replacement_token=replacement_token,
            presented_token=raw_token,
            remote_address="203.0.113.91",
        )

    def observed_active_credential(*args, **kwargs):
        if (
            rotation_thread_id
            and threading.get_ident() == rotation_thread_id[0]
            and kwargs.get("for_update")
        ):
            rotation_reached_credential_lock.set()
        return real_active_credential(*args, **kwargs)

    with (
        patch.object(
            ActorAccountLinkReceipt.objects,
            "create",
            side_effect=paused_receipt_create,
        ),
        patch("identity.services.active_credential", side_effect=observed_active_credential),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        linked = executor.submit(link_worker)
        assert link_created.wait(timeout=10)
        rotated = executor.submit(rotate_worker)
        assert rotation_reached_credential_lock.wait(timeout=10)
        assert not rotated.done()
        release_link.set()
        assert linked.result(timeout=10).account_id == account.pk
        with pytest.raises(InvalidInstallationCredential):
            rotated.result(timeout=10)

    assert ActorAccountLink.objects.filter(actor=actor, account=account).exists()
    assert InstallationActor.objects.filter(pk=actor.pk).exists()
