import hashlib
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from allauth.account.models import EmailAddress
from billing.models import AccountEntitlement, ProviderDeletionRequest, RevenueCatEvent
from covers.models import CoverObservation
from covers.privacy import erased_independence_group_key
from covers.services import resolve_at
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import SESSION_KEY
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.test import Client
from django.utils import timezone
from operations.models import AuditEvent
from submissions.models import Submission, SubmissionPrivateContext, SubmissionRateBucket
from submissions.schemas import CoverSubmissionSchema
from venues.models import Venue

from identity.credentials import issue_installation
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
from identity.services import _erase_actor_private_context, delete_account
from identity.tokens import issue_session_token, lookup_session_token


def _contains_nested_value(value, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, dict):
        return any(_contains_nested_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nested_value(item, expected) for item in value)
    return False


def create_actor_cover_observation(actor, venue, observed_at, price_cents):
    submission = Submission.objects.create(
        id=uuid.uuid4(),
        request_fingerprint=uuid.uuid4().hex * 2,
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=observed_at,
        received_at_server=observed_at + timedelta(seconds=1),
        time_quality=Submission.TimeQuality.PLAUSIBLE,
    )
    SubmissionPrivateContext.objects.create(submission=submission, actor=actor)
    return CoverObservation.objects.create(
        submission=submission,
        reported_price_cents=price_cents,
        interaction_kind=CoverObservation.InteractionKind.DIRECT,
        independence_group_key=actor.id,
    )


@pytest.mark.django_db
def test_repeated_actor_erasure_cannot_manufacture_independent_cover_consensus():
    venue = Venue.objects.create(slug="erased", name="Erased")
    second_venue = Venue.objects.create(slug="other", name="Other")
    observed_at = timezone.now()
    first_actor = issue_installation("ic_install_" + "a" * 43)
    second_actor = issue_installation("ic_install_" + "b" * 43)
    same_night = [
        create_actor_cover_observation(first_actor, venue, observed_at, 1_000),
        create_actor_cover_observation(
            first_actor, venue, observed_at + timedelta(minutes=1), 1_500
        ),
        create_actor_cover_observation(
            second_actor, venue, observed_at + timedelta(minutes=2), 2_000
        ),
    ]
    other_context = create_actor_cover_observation(
        second_actor, second_venue, observed_at + timedelta(minutes=3), 2_500
    )
    next_night = create_actor_cover_observation(
        second_actor, venue, observed_at + timedelta(days=1), 3_000
    )

    _erase_actor_private_context(first_actor)
    _erase_actor_private_context(second_actor)
    for observation in [*same_night, other_context, next_night]:
        observation.refresh_from_db()

    same_night_keys = {observation.independence_group_key for observation in same_night}
    assert same_night_keys == {erased_independence_group_key(venue.id, observed_at)}
    assert other_context.independence_group_key != next(iter(same_night_keys))
    assert next_night.independence_group_key != next(iter(same_night_keys))


@pytest.mark.django_db
def test_account_deletion_preserves_observation_but_erases_linkable_private_context():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    account = Account.objects.create_user("person@example.com")
    AccountEntitlement.objects.create(account=account, is_active=True)
    client = Client()
    issued = client.post(
        "/api/v2/installations",
        data={
            "requestId": str(uuid.uuid4()),
            "installationToken": "ic_install_" + "a" * 43,
        },
        content_type="application/json",
    ).json()
    actor = InstallationActor.objects.get(pk=issued["actorId"])
    link = ActorAccountLink.objects.create(actor=actor, account=account)
    link_request_id = uuid.uuid4()
    ActorAccountLinkReceipt.objects.create(request_id=link_request_id, link=link)
    report_payload = {
        "submissionId": str(uuid.uuid4()),
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "location": {
            "latitude": 40.11044,
            "longitude": -88.23825,
            "accuracyMeters": 8,
        },
        "cover": {"priceCents": 2000, "interaction": "manual"},
    }
    report = client.post(
        "/api/v2/cover-submissions",
        data=report_payload,
        content_type="application/json",
        headers={"X-Installation-Token": issued["token"]},
        REMOTE_ADDR="203.0.113.50",
    )
    parsed_payload = CoverSubmissionSchema.model_validate(report_payload)
    canonical_payload = json.dumps(
        parsed_payload.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    legacy_unkeyed_fingerprint = hashlib.sha256(canonical_payload.encode()).hexdigest()
    Submission.objects.filter(pk=report_payload["submissionId"]).update(
        request_fingerprint=legacy_unkeyed_fingerprint
    )
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    session_token = issue_session_token(session)
    revenuecat_event = RevenueCatEvent.objects.create(
        provider_event_id="deletion-event",
        event_type="INITIAL_PURCHASE",
        app_user_id=str(account.id),
        payload={"event": {"app_user_id": str(account.id)}},
    )
    alias_event = RevenueCatEvent.objects.create(
        provider_event_id="deletion-alias-event",
        event_type="TRANSFER",
        app_user_id=str(uuid.uuid4()),
        payload={
            "event": {
                "originalAppUserId": str(uuid.uuid4()),
                "aliases": [str(account.id)],
            }
        },
    )
    staff = Account.objects.create_user("staff@example.com", is_staff=True)
    account_content_type = ContentType.objects.get_for_model(Account)
    admin_log = LogEntry.objects.create(
        user=staff,
        content_type=account_content_type,
        object_id=str(account.id),
        object_repr=account.email,
        action_flag=CHANGE,
        change_message="Changed display name.",
    )
    target_audit = AuditEvent.objects.create(
        kind="admin.change",
        actor_kind="account",
        actor_reference=str(staff.id),
        target_reference=f"identity.account:{account.id}",
        metadata={"model": "identity.account"},
    )
    actor_audit = AuditEvent.objects.create(
        kind="admin.change",
        actor_kind="account",
        actor_reference=str(account.id),
        target_reference="venues.venue:public-id",
        metadata={"model": "venues.venue"},
    )
    identity_rate_keys = {
        f"report-rate:actor:{actor.id}:1",
        f"report-rate:account:{account.id}:1",
        f"report-rate:time-machine-account:{account.id}:1",
    }
    retained_rate_keys = {
        f"report-rate:venue:{venue.id}:1",
        "report-rate:network:unrelated-verifier:1",
    }
    SubmissionRateBucket.objects.bulk_create(
        [
            SubmissionRateBucket(
                key=key,
                count=1,
                expires_at=timezone.now() + timedelta(hours=1),
            )
            for key in identity_rate_keys | retained_rate_keys
        ]
    )

    deletion_request_id = uuid.uuid4()
    deleted = client.delete(
        "/api/v2/me",
        data={"requestId": str(deletion_request_id)},
        content_type="application/json",
        headers={"X-Session-Token": session_token},
    )

    assert report.status_code == 201
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["requestId"] == str(deletion_request_id)
    observation = CoverObservation.objects.get()
    observation.submission.refresh_from_db()
    assert observation.reported_price_cents == 2000
    assert observation.submission.request_fingerprint != legacy_unkeyed_fingerprint
    assert observation.independence_group_key == erased_independence_group_key(
        venue.id, observation.submission.observed_at_client
    )
    assert resolve_at(venue, observation.submission.observed_at_client, timezone.now()).source in {
        "live",
        "mixed",
    }
    context = SubmissionPrivateContext.objects.get(submission=observation.submission)
    assert context.actor_id is None
    assert context.account_id is None
    assert context.latitude is None
    assert context.longitude is None
    assert context.network_verifier == ""
    assert context.erased_at is not None
    assert lookup_session_token(session_token) is None
    assert not InstallationActor.objects.filter(pk=actor.pk).exists()
    assert not InstallationCredential.objects.exists()
    assert not InstallationOperationReceipt.objects.exists()
    assert not ActorAccountLinkReceipt.objects.filter(pk=link_request_id).exists()
    receipt = AccountDeletionReceipt.objects.get(pk=deletion_request_id)
    assert receipt.expires_at - receipt.completed_at == timedelta(days=30)
    assert {field.name for field in AccountDeletionReceipt._meta.fields} == {
        "request_id",
        "completed_at",
        "expires_at",
    }
    status = Client().get(f"/api/v2/account-deletions/{deletion_request_id}")
    absent = Client().get(f"/api/v2/account-deletions/{uuid.uuid4()}")
    assert status.status_code == 200
    assert status.headers["Cache-Control"] == "no-store"
    assert status.json() == deleted.json()
    assert absent.status_code == 404
    assert absent.headers["Cache-Control"] == "no-store"
    assert absent.json()["code"] == "deletion_not_found"
    deletion = ProviderDeletionRequest.objects.get(provider_customer_id=str(account.id))
    assert deletion.status == "pending"
    assert not AccountEntitlement.objects.filter(account_id=account.id).exists()
    assert not SubmissionRateBucket.objects.filter(key__in=identity_rate_keys).exists()
    assert (
        not SubmissionRateBucket.objects.exclude(key__in=retained_rate_keys)
        .filter(
            Q(key__startswith=f"report-rate:actor:{actor.id}:")
            | Q(key__startswith=f"report-rate:account:{account.id}:")
            | Q(key__startswith=f"report-rate:time-machine-account:{account.id}:")
        )
        .exists()
    )
    assert SubmissionRateBucket.objects.filter(key__in=retained_rate_keys).count() == 2
    assert not SessionStore().exists(session.session_key)
    assert not RevenueCatEvent.objects.filter(pk=revenuecat_event.pk).exists()
    assert not RevenueCatEvent.objects.filter(pk=alias_event.pk).exists()
    admin_log.refresh_from_db()
    target_audit.refresh_from_db()
    actor_audit.refresh_from_db()
    assert admin_log.object_id is None
    assert admin_log.object_repr == "Deleted account"
    assert account.email not in admin_log.change_message
    assert target_audit.actor_reference == str(staff.id)
    assert target_audit.target_reference == "identity.account:deleted"
    assert actor_audit.actor_kind == "deleted_account"
    assert actor_audit.actor_reference == ""
    assert str(account.id) not in {
        target_audit.target_reference,
        actor_audit.actor_reference,
    }
    history = client.get("/api/v2/venues/kams/cover/history").json()
    assert history["reports"][0]["priceCents"] == 2000
    assert "latitude" not in history["reports"][0]


@pytest.mark.django_db
def test_account_deletion_removes_pending_login_code_sessions_by_user_and_email():
    account = Account.objects.create_user("challenge@example.com")
    EmailAddress.objects.create(
        user=account,
        email=account.email,
        verified=True,
        primary=True,
    )
    client = Client()
    requested = client.post(
        "/_allauth/app/v1/auth/code/request",
        data={"email": account.email},
        content_type="application/json",
    )
    assert requested.status_code == 401
    pending_token = requested.json()["meta"]["session_token"]
    pending_verifier = SessionTokenVerifier.objects.get(revoked_at__isnull=True)
    pending_session = SessionStore(session_key=pending_verifier.session_key)
    pending_data = pending_session.load()
    assert SESSION_KEY not in pending_data
    assert _contains_nested_value(pending_data["account_login"], str(account.id))
    assert _contains_nested_value(pending_data["account_login"], account.email)

    email_only_session = SessionStore()
    email_only_session["account_login"] = {
        "user_pk": None,
        "email": account.email.upper(),
        "state": {"email": account.email.upper(), "code": "BCDF-GHJK"},
    }
    email_only_session.save()
    email_only_token = issue_session_token(email_only_session)
    email_only_verifier = SessionTokenVerifier.objects.get(
        session_key=email_only_session.session_key
    )
    assert email_only_verifier.account_id is None

    unrelated_session = SessionStore()
    unrelated_session["account_login"] = {
        "user_pk": None,
        "email": "other@example.com",
        "state": {"email": "other@example.com", "code": "LMNP-QRST"},
    }
    unrelated_session.save()
    unrelated_token = issue_session_token(unrelated_session)

    authenticated_session = SessionStore()
    authenticated_session[SESSION_KEY] = str(account.pk)
    authenticated_session.save()
    authenticated_token = issue_session_token(authenticated_session)
    deleted = client.delete(
        "/api/v2/me",
        data={"requestId": str(uuid.uuid4())},
        content_type="application/json",
        headers={"X-Session-Token": authenticated_token},
    )

    assert deleted.status_code == 200
    erased_session_keys = {pending_verifier.session_key, email_only_session.session_key}
    assert not Session.objects.filter(session_key__in=erased_session_keys).exists()
    assert not SessionTokenVerifier.objects.filter(session_key__in=erased_session_keys).exists()
    assert lookup_session_token(pending_token) is None
    assert lookup_session_token(email_only_token) is None
    assert Session.objects.filter(session_key=unrelated_session.session_key).exists()
    assert lookup_session_token(unrelated_token) is not None


@pytest.mark.django_db
def test_account_deletion_removes_pending_signup_email_verification_session():
    client = Client()
    signup = client.post(
        "/_allauth/app/v1/auth/signup",
        data={"email": "new-challenge@example.com"},
        content_type="application/json",
    )
    assert signup.status_code == 401
    pending_token = signup.json()["meta"]["session_token"]
    pending_verifier = SessionTokenVerifier.objects.get(revoked_at__isnull=True)
    pending_session = SessionStore(session_key=pending_verifier.session_key)
    pending_data = pending_session.load()
    account = Account.objects.get(email="new-challenge@example.com")
    assert SESSION_KEY not in pending_data
    assert _contains_nested_value(pending_data["account_email_verification_code"], str(account.id))
    assert _contains_nested_value(pending_data["account_email_verification_code"], account.email)

    authenticated_session = SessionStore()
    authenticated_session[SESSION_KEY] = str(account.pk)
    authenticated_session.save()
    deleted = client.delete(
        "/api/v2/me",
        data={"requestId": str(uuid.uuid4())},
        content_type="application/json",
        headers={"X-Session-Token": issue_session_token(authenticated_session)},
    )

    assert deleted.status_code == 200
    assert not Session.objects.filter(session_key=pending_verifier.session_key).exists()
    assert not SessionTokenVerifier.objects.filter(pk=pending_verifier.pk).exists()
    assert lookup_session_token(pending_token) is None


@pytest.mark.django_db
def test_abandoned_unverified_signup_cleanup_requires_age_and_no_account_dependencies():
    abandoned = Account.objects.create_user("abandoned@example.com")
    EmailAddress.objects.create(
        user=abandoned,
        email=abandoned.email,
        verified=False,
        primary=True,
    )
    old_signup = timezone.now() - timedelta(days=2)
    Account.objects.filter(pk=abandoned.pk).update(created_at=old_signup)
    pending_session = SessionStore()
    pending_session["account_email_verification_code"] = {
        "user_id": str(abandoned.pk),
        "email": abandoned.email,
        "code": "BCDF-GHJK",
    }
    pending_session.set_expiry(-1)
    pending_session.save()
    pending_token = issue_session_token(pending_session)

    recent = Account.objects.create_user("recent@example.com")
    EmailAddress.objects.create(user=recent, email=recent.email, verified=False, primary=True)
    previously_authenticated = Account.objects.create_user("logged-in@example.com")
    EmailAddress.objects.create(
        user=previously_authenticated,
        email=previously_authenticated.email,
        verified=False,
        primary=True,
    )
    Account.objects.filter(pk=previously_authenticated.pk).update(
        created_at=old_signup,
        last_login=old_signup,
    )
    linked = Account.objects.create_user("linked@example.com")
    EmailAddress.objects.create(user=linked, email=linked.email, verified=False, primary=True)
    Account.objects.filter(pk=linked.pk).update(created_at=old_signup)
    ActorAccountLink.objects.create(
        actor=issue_installation("ic_install_" + "q" * 43),
        account=linked,
    )
    provider_referenced = Account.objects.create_user("provider-referenced@example.com")
    EmailAddress.objects.create(
        user=provider_referenced,
        email=provider_referenced.email,
        verified=False,
        primary=True,
    )
    Account.objects.filter(pk=provider_referenced.pk).update(created_at=old_signup)
    RevenueCatEvent.objects.create(
        provider_event_id="abandoned-reference",
        event_type="TRANSFER",
        app_user_id="",
        payload={"aliases": [str(provider_referenced.pk)]},
    )

    from identity.services import cleanup_abandoned_unverified_accounts

    deleted = cleanup_abandoned_unverified_accounts(now=timezone.now())

    assert deleted == 1
    assert not Account.objects.filter(pk=abandoned.pk).exists()
    assert lookup_session_token(pending_token) is None
    assert not Session.objects.filter(session_key=pending_session.session_key).exists()
    assert Account.objects.filter(pk=recent.pk).exists()
    assert Account.objects.filter(pk=previously_authenticated.pk).exists()
    assert Account.objects.filter(pk=linked.pk).exists()
    assert Account.objects.filter(pk=provider_referenced.pk).exists()


@pytest.mark.django_db
def test_abandoned_signup_cleanup_rechecks_dependencies_after_lock():
    abandoned = Account.objects.create_user("recheck@example.com")
    EmailAddress.objects.create(
        user=abandoned,
        email=abandoned.email,
        verified=False,
        primary=True,
    )
    Account.objects.filter(pk=abandoned.pk).update(created_at=timezone.now() - timedelta(days=2))
    actor = issue_installation("ic_install_" + "r" * 43)

    from identity import services

    real_guard = services._abandoned_account_has_dependencies

    def add_link_before_guard(locked_account):
        ActorAccountLink.objects.get_or_create(actor=actor, account=locked_account)
        return real_guard(locked_account)

    with patch(
        "identity.services._abandoned_account_has_dependencies",
        side_effect=add_link_before_guard,
    ):
        deleted = services.cleanup_abandoned_unverified_accounts(now=timezone.now())

    assert deleted == 0
    assert Account.objects.filter(pk=abandoned.pk).exists()
    assert ActorAccountLink.objects.filter(account=abandoned, actor=actor).exists()


@pytest.mark.django_db
def test_account_deletion_and_completion_tombstone_are_one_atomic_transaction():
    account = Account.objects.create_user("atomic@example.com")
    actor = issue_installation("ic_install_" + "z" * 43)
    link = ActorAccountLink.objects.create(actor=actor, account=account)
    link_request_id = uuid.uuid4()
    ActorAccountLinkReceipt.objects.create(request_id=link_request_id, link=link)
    account_id = account.pk
    actor_id = actor.pk

    with (
        patch(
            "identity.services.AccountDeletionReceipt.objects.create",
            side_effect=RuntimeError("simulated tombstone write failure"),
        ),
        pytest.raises(RuntimeError, match="tombstone write failure"),
    ):
        delete_account(account, request_id=uuid.uuid4())

    assert Account.objects.filter(pk=account_id).exists()
    assert InstallationActor.objects.filter(pk=actor_id).exists()
    assert InstallationCredential.objects.filter(actor_id=actor_id).exists()
    assert ActorAccountLink.objects.filter(actor_id=actor_id, account_id=account_id).exists()
    assert ActorAccountLinkReceipt.objects.filter(
        pk=link_request_id,
        link=link,
    ).exists()
    assert not AccountDeletionReceipt.objects.exists()
    assert not ProviderDeletionRequest.objects.exists()
