import uuid
from datetime import timedelta

import pytest
from covers.models import CoverModelRelease, ShadowCoverPrediction
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from identity.models import (
    AccountDeletionReceipt,
    AllauthRateLimitCache,
    IdentityRateBucket,
    SessionTokenVerifier,
)
from venues.models import Venue

from operations.jobs import JobAlreadyRunning, managed_job
from operations.models import JobRun


@pytest.mark.django_db
def test_managed_job_blocks_a_concurrent_name_but_allows_a_later_run(settings):
    settings.DATABASE_CONNECTION_MODE = "pooled"

    with managed_job("pooled-job"):
        with pytest.raises(JobAlreadyRunning):
            with managed_job("pooled-job"):
                pass

    with managed_job("pooled-job"):
        pass

    assert list(JobRun.objects.filter(name="pooled-job").values_list("status", flat=True)) == [
        "succeeded",
        "succeeded",
    ]


@pytest.mark.django_db
def test_managed_job_recovers_a_crashed_receipt_after_the_bounded_lease(settings):
    settings.JOB_RUN_STALE_AFTER_SECONDS = 60
    stale = JobRun.objects.create(name="recoverable-job", status="running")
    JobRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - timedelta(minutes=2))

    with managed_job("recoverable-job"):
        pass

    stale.refresh_from_db()
    assert stale.status == "failed"
    assert stale.error == "StaleJobRun: execution lease expired before completion"
    assert JobRun.objects.filter(name="recoverable-job", status="succeeded").count() == 1


@pytest.mark.django_db
def test_nightly_duplicate_is_a_failed_execution_not_a_false_green():
    JobRun.objects.create(name="nightly", status="running")

    with pytest.raises(CommandError, match="already running"):
        call_command("nightly", verbosity=0)


@pytest.mark.django_db
def test_cleanup_job_is_idempotent_and_receipted():
    active_session = Session.objects.create(
        session_key="active-session",
        session_data="e30=",
        expire_date=timezone.now() + timedelta(days=1),
    )
    Session.objects.create(
        session_key="expired-session",
        session_data="e30=",
        expire_date=timezone.now() - timedelta(days=1),
    )
    SessionTokenVerifier.objects.create(
        verifier="a" * 64,
        session_key=active_session.session_key,
    )
    SessionTokenVerifier.objects.create(
        verifier="b" * 64,
        session_key=active_session.session_key,
        revoked_at=timezone.now(),
    )
    SessionTokenVerifier.objects.create(
        verifier="c" * 64,
        session_key="expired-session",
    )
    SessionTokenVerifier.objects.create(
        verifier="d" * 64,
        session_key="already-missing-session",
    )
    AllauthRateLimitCache.objects.create(
        cache_key="expired-rate-limit",
        value="ignored",
        expires=timezone.now() - timedelta(seconds=1),
    )
    IdentityRateBucket.objects.create(
        key="expired-identity-rate-limit",
        count=8,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    deletion_receipt = AccountDeletionReceipt.objects.create(
        request_id=uuid.uuid4(),
        completed_at=timezone.now() - timedelta(days=31),
        expires_at=timezone.now() - timedelta(days=1),
    )
    active_deletion_receipt = AccountDeletionReceipt.objects.create(
        request_id=uuid.uuid4(),
        completed_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=30),
    )

    call_command("cleanup", verbosity=0)
    call_command("cleanup", verbosity=0)

    assert not Session.objects.filter(session_key="expired-session").exists()
    assert not AllauthRateLimitCache.objects.filter(cache_key="expired-rate-limit").exists()
    assert not IdentityRateBucket.objects.filter(key="expired-identity-rate-limit").exists()
    assert not AccountDeletionReceipt.objects.filter(pk=deletion_receipt.pk).exists()
    assert AccountDeletionReceipt.objects.filter(pk=active_deletion_receipt.pk).exists()
    assert list(SessionTokenVerifier.objects.values_list("verifier", flat=True)) == ["a" * 64]
    runs = list(JobRun.objects.filter(name="cleanup").order_by("started_at"))
    assert [run.status for run in runs] == ["succeeded", "succeeded"]
    assert runs[0].result_summary["expiredSessionsDeleted"] == 1
    assert runs[0].result_summary["sessionTokenVerifiersDeleted"] == 3
    assert runs[0].result_summary["expiredRateLimitRowsDeleted"] == 2
    assert runs[0].result_summary["expiredAccountDeletionReceiptsDeleted"] == 1
    assert runs[0].result_summary["abandonedUnverifiedAccountsDeleted"] == 0
    assert runs[1].result_summary["expiredSessionsDeleted"] == 0
    assert runs[1].result_summary["sessionTokenVerifiersDeleted"] == 0
    assert runs[1].result_summary["expiredRateLimitRowsDeleted"] == 0
    assert runs[1].result_summary["expiredAccountDeletionReceiptsDeleted"] == 0
    assert runs[1].result_summary["abandonedUnverifiedAccountsDeleted"] == 0


@pytest.mark.django_db
def test_cleanup_prunes_only_shadow_predictions_older_than_thirty_days():
    now = timezone.now()
    venue = Venue.objects.create(slug="shadow-retention", name="Shadow Retention")
    release = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="shadow-retention",
        code_revision="test",
        training_data_revision="shadow-retention-training",
    )
    expired = ShadowCoverPrediction.objects.create(
        venue=venue,
        model_release=release,
        target_time=now - timedelta(days=31),
        knowledge_cutoff=now - timedelta(days=31),
    )
    retained = ShadowCoverPrediction.objects.create(
        venue=venue,
        model_release=release,
        target_time=now - timedelta(days=29),
        knowledge_cutoff=now - timedelta(days=29),
    )
    ShadowCoverPrediction.objects.filter(pk=expired.pk).update(
        created_at=now - timedelta(days=31)
    )
    ShadowCoverPrediction.objects.filter(pk=retained.pk).update(
        created_at=now - timedelta(days=29)
    )

    call_command("cleanup", verbosity=0)

    assert not ShadowCoverPrediction.objects.filter(pk=expired.pk).exists()
    assert ShadowCoverPrediction.objects.filter(pk=retained.pk).exists()
    assert CoverModelRelease.objects.filter(pk=release.pk).exists()
    assert JobRun.objects.get(name="cleanup").result_summary[
        "expiredShadowPredictionsDeleted"
    ] == 1
