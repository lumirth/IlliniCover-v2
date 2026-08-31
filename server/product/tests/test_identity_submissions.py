import json
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest
from covers.services import service_date_for
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import close_old_connections, connection
from django.test import Client
from django.utils import timezone
from identity.credentials import installation_verifier, lookup_installation
from identity.services import delete_account, link_installation, rotate_installation
from submissions import services as submission_services
from submissions.schemas import CoverSubmissionSchema
from submissions.services import IdempotencyConflict, accept_cover_submission

from product.models import (
    Account,
    InstallationActor,
    SessionTokenVerifier,
    Submission,
    SubmissionPrivateContext,
)


def payload(venue, *, submission_id=None, location=None):
    return CoverSubmissionSchema.model_validate(
        {
            "submissionId": str(submission_id or uuid.uuid4()),
            "venueId": str(venue.pk),
            "observedAt": timezone.now().replace(microsecond=0).isoformat(),
            "location": location,
            "cover": {"priceCents": 1000, "interaction": "direct"},
        }
    )


def api_payload(venue, endpoint):
    observed = timezone.now().replace(microsecond=0)
    common = {
        "submissionId": str(uuid.uuid4()),
        "venueId": str(venue.pk),
        "observedAt": observed.isoformat(),
        "location": {
            "latitude": 40.11044,
            "longitude": -88.23825,
            "accuracyMeters": 10,
            "permission": "when_in_use",
        },
    }
    if endpoint == "cover":
        return "/api/cover-submissions", common | {
            "cover": {"priceCents": 1000, "interaction": "direct"}
        }
    return "/api/deal-evidence", common | {
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(observed).isoformat(),
        "submittedDealShape": {
            "displayName": "Wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 300,
        },
    }


@pytest.mark.django_db
def test_installation_api_hashes_credentials_and_has_no_recovery_surface():
    token = "ic_install_" + "a" * 43
    response = Client().post(
        "/api/installations", {"installationToken": token}, content_type="application/json"
    )
    assert response.status_code == 201
    actor = lookup_installation(token)
    assert actor and actor.verifier == installation_verifier(token) and token not in actor.verifier
    assert Client().get("/api/installations/current").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_rotation_returns_unlinked_actor_and_deidentifies_context_selected_groups(
    venue, installation
):
    token, actor = installation
    account = Account.objects.create_user("person@example.com")
    link_installation(account, token)
    signed_in = Submission.objects.create(
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=datetime.now(UTC),
        independence_group=account.pk,
    )
    SubmissionPrivateContext.objects.create(submission=signed_in, actor=actor, account=account)
    actor_grouped = Submission.objects.create(
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=datetime.now(UTC),
        independence_group=actor.pk,
    )

    replacement = "ic_install_" + "b" * 43
    new = rotate_installation(replacement, token, None)
    assert new.account_id is None
    assert lookup_installation(token) is None
    assert not SubmissionPrivateContext.objects.exists()
    signed_in.refresh_from_db()
    actor_grouped.refresh_from_db()
    assert signed_in.independence_group is None
    assert actor_grouped.independence_group is None


@pytest.mark.django_db(transaction=True)
def test_account_deletion_erases_groups_context_and_only_its_indexed_sessions(
    venue, installation, monkeypatch
):
    token, actor = installation
    account = Account.objects.create_user("erase@example.com")
    link_installation(account, token)
    contextual = Submission.objects.create(
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=datetime.now(UTC),
        independence_group=account.pk,
        cover_price_cents=1000,
    )
    SubmissionPrivateContext.objects.create(submission=contextual, actor=actor, account=account)
    actor_grouped = Submission.objects.create(
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=datetime.now(UTC),
        independence_group=actor.pk,
    )

    owned_session = SessionStore()
    owned_session[SESSION_KEY] = str(account.pk)
    owned_session.save()
    SessionTokenVerifier.objects.create(
        verifier="a" * 64,
        session_key=owned_session.session_key,
        account=account,
    )
    unrelated_session = SessionStore()
    unrelated_session["unrelated"] = True
    unrelated_session.save()

    monkeypatch.setattr("billing.revenuecat.process_deletion", lambda request: True)
    delete_account(account)

    contextual.refresh_from_db()
    actor_grouped.refresh_from_db()
    assert contextual.cover_price_cents == 1000
    assert contextual.independence_group is actor_grouped.independence_group is None
    assert not SubmissionPrivateContext.objects.exists()
    assert not Account.objects.filter(pk=account.pk).exists()
    assert not InstallationActor.objects.filter(pk=actor.pk).exists()
    assert not Session.objects.filter(session_key=owned_session.session_key).exists()
    assert Session.objects.filter(session_key=unrelated_session.session_key).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock regression")
@pytest.mark.django_db(transaction=True)
def test_account_deletion_serializes_with_inflight_submission(
    venue, installation, monkeypatch
):
    token, actor = installation
    account = Account.objects.create_user("concurrent-delete@example.com")
    link_installation(account, token)
    submitted = payload(
        venue,
        location={
            "latitude": 40.11044,
            "longitude": -88.23825,
            "accuracyMeters": 12,
            "permission": "when_in_use",
        },
    )
    identity_locked = Event()
    finish_submission = Event()
    deletion_pid: Queue[int] = Queue()
    original_limits = submission_services.enforce_submission_limits

    def hold_submission(*args, **kwargs):
        result = original_limits(*args, **kwargs)
        identity_locked.set()
        if not finish_submission.wait(10):
            raise AssertionError("timed out while holding submission identity locks")
        return result

    def submit():
        close_old_connections()
        try:
            return accept_cover_submission(
                InstallationActor.objects.get(pk=actor.pk),
                submitted,
                remote_address=None,
                session_account=Account.objects.get(pk=account.pk),
            )
        finally:
            close_old_connections()

    def delete():
        close_old_connections()
        try:
            connection.ensure_connection()
            deletion_pid.put(connection.connection.info.backend_pid)
            delete_account(Account.objects.get(pk=account.pk))
        finally:
            close_old_connections()

    monkeypatch.setattr(submission_services, "enforce_submission_limits", hold_submission)
    monkeypatch.setattr("billing.revenuecat.process_deletion", lambda request: True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        submission_future = pool.submit(submit)
        assert identity_locked.wait(5)
        deletion_future = pool.submit(delete)
        pid = deletion_pid.get(timeout=5)
        try:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid]
                    )
                    state = cursor.fetchone()
                if state == ("Lock",):
                    break
                if deletion_future.done():
                    deletion_future.result()
                    raise AssertionError("deletion did not wait for the in-flight submission")
                sleep(0.01)
            else:
                raise AssertionError("deletion never waited on the submission identity lock")
        finally:
            finish_submission.set()
        submission_future.result(timeout=10)
        deletion_future.result(timeout=10)

    retained = Submission.objects.get(pk=submitted.submission_id)
    assert retained.independence_group is None
    assert not SubmissionPrivateContext.objects.filter(submission=retained).exists()
    assert not Account.objects.filter(pk=account.pk).exists()
    assert not InstallationActor.objects.filter(pk=actor.pk).exists()


@pytest.mark.django_db
def test_submission_uuid_exact_retry_succeeds_but_changed_payload_conflicts(
    venue, installation
):
    _, actor = installation
    submitted = payload(venue)
    first = accept_cover_submission(actor, submitted, remote_address=None)
    second = accept_cover_submission(actor, submitted, remote_address=None)
    assert not first["duplicate"] and second["duplicate"]

    changed = submitted.model_copy(deep=True)
    changed.cover.price_cents = 1500
    with pytest.raises(IdempotencyConflict):
        accept_cover_submission(actor, changed, remote_address=None)


@pytest.mark.django_db
def test_quantized_location_retry_survives_private_context_erasure(venue, installation):
    _, actor = installation
    submitted = payload(
        venue,
        location={
            "latitude": 40.1104404,
            "longitude": -88.2382504,
            "accuracyMeters": 12.345,
            "permission": "when_in_use",
        },
    )
    assert not accept_cover_submission(actor, submitted, remote_address=None)["duplicate"]
    assert accept_cover_submission(actor, submitted, remote_address=None)["duplicate"]

    SubmissionPrivateContext.objects.filter(submission_id=submitted.submission_id).delete()
    assert accept_cover_submission(actor, submitted, remote_address=None)["duplicate"]


@pytest.mark.django_db
def test_location_accuracy_storage_boundary_is_accepted(venue, installation):
    submitted = payload(
        venue,
        location={
            "latitude": 40.11044,
            "longitude": -88.23825,
            "accuracyMeters": 999_999.99,
        },
    )
    accept_cover_submission(installation[1], submitted, remote_address=None)
    context = SubmissionPrivateContext.objects.get(submission_id=submitted.submission_id)
    assert context.location_accuracy_m == Decimal("999999.99")


@pytest.mark.parametrize("endpoint", ["cover", "deal"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accuracyMeters", "not-a-number"),
        ("accuracyMeters", math.nan),
        ("accuracyMeters", math.inf),
        ("accuracyMeters", 1_000_000),
        ("accuracyMeters", -0.01),
        ("permission", "always"),
    ],
    ids=["malformed", "nan", "infinite", "oversized", "negative", "permission"],
)
@pytest.mark.django_db
def test_invalid_location_returns_422_for_cover_and_deal(
    venue, installation, endpoint, field, value
):
    path, body = api_payload(venue, endpoint)
    body["location"][field] = value
    response = Client().post(
        path,
        json.dumps(body),
        content_type="application/json",
        HTTP_X_INSTALLATION_TOKEN=installation[0],
    )
    assert response.status_code == 422, response.content
