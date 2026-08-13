import uuid
from datetime import UTC, timedelta
from datetime import timezone as datetime_timezone

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.signals import post_save
from django.test import override_settings
from django.utils import timezone
from operations.models import AuditEvent, JobRun
from submissions.models import Submission
from venues.models import Venue

from covers.modeling import HistoricalModel, HistoricalModelConfig, HistoricalObservation
from covers.models import (
    CoverModelEvaluationReceipt,
    CoverModelRelease,
    CoverObservation,
    CoverTrainingRevision,
    ShadowCoverPrediction,
)
from covers.releases import evaluate_non_authoritative_releases, evaluation_receipt_is_valid
from covers.services import service_date_for


def _model_artifact(*, release_id: str, price_cents: int, observed_at):
    return HistoricalModel.fit(
        [
            HistoricalObservation(
                observation_id=f"{release_id}-training",
                venue_id="training-venue",
                observed_at=observed_at,
                available_at=observed_at,
                service_date=service_date_for(observed_at),
                price_cents=price_cents,
            )
        ],
        HistoricalModelConfig(release_id=release_id, use_venue_effect=False),
    ).to_artifact()


def _held_out_report(venue: Venue, observed_at, *, price_cents: int = 1_500) -> None:
    submission = Submission.objects.create(
        id=uuid.uuid4(),
        request_fingerprint=uuid.uuid4().hex * 2,
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=observed_at,
        received_at_server=observed_at + timedelta(minutes=1),
        time_quality=Submission.TimeQuality.PLAUSIBLE,
    )
    CoverObservation.objects.create(
        submission=submission,
        reported_price_cents=price_cents,
        interaction_kind=CoverObservation.InteractionKind.DIRECT,
        admission_snapshot={"resolverVersion": "cover_trust_v1"},
    )


def _winning_evaluation_setup():
    cutoff = timezone.now().replace(second=0, microsecond=0)
    training_cutoff = cutoff - timedelta(days=10)
    training_revision = CoverTrainingRevision.objects.create(
        data_revision="challenger-training-revision",
        knowledge_cutoff=training_cutoff,
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    training_observed_at = training_cutoff - timedelta(days=7)
    incumbent = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="incumbent",
        code_revision="incumbent-code",
        training_data_revision="incumbent-training",
        parameters_or_artifact=_model_artifact(
            release_id="incumbent",
            price_cents=1_000,
            observed_at=training_observed_at,
        ),
        is_authoritative=True,
        promoted_at=training_cutoff - timedelta(days=1),
    )
    challenger = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="challenger",
        code_revision="challenger-code",
        training_data_revision=training_revision.data_revision,
        parameters_or_artifact=_model_artifact(
            release_id="challenger",
            price_cents=1_500,
            observed_at=training_observed_at,
        ),
        evaluation_metrics={
            "status": "shadow_pending",
            "baselineReleaseId": str(incumbent.id),
        },
    )
    venues = [
        Venue.objects.create(slug=f"evaluation-{index}", name=f"Evaluation {index}")
        for index in range(4)
    ]
    for index in range(20):
        _held_out_report(
            venues[index % len(venues)],
            training_cutoff + timedelta(days=index // 5 + 1),
        )

    return cutoff, training_revision, incumbent, challenger


@pytest.mark.django_db
def test_shadow_pass_only_evaluates_the_current_active_challenger():
    cutoff = timezone.now().replace(second=0, microsecond=0)
    venue = Venue.objects.create(slug="shadow", name="Shadow")
    incumbent = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="current-incumbent",
        code_revision="current-code",
        training_data_revision="current-training",
        parameters_or_artifact=_model_artifact(
            release_id="current-incumbent",
            price_cents=1_000,
            observed_at=cutoff - timedelta(days=7),
        ),
        is_authoritative=True,
        promoted_at=cutoff - timedelta(days=6),
    )
    retired_incumbent = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="retired-incumbent",
        code_revision="retired-code",
        training_data_revision="retired-training",
        parameters_or_artifact=_model_artifact(
            release_id="retired-incumbent",
            price_cents=500,
            observed_at=cutoff - timedelta(days=14),
        ),
        retired_at=cutoff - timedelta(days=6),
    )
    superseded_active = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="superseded-active-challenger",
        code_revision="superseded-active-code",
        training_data_revision="superseded-active-training",
        parameters_or_artifact=_model_artifact(
            release_id="superseded-active-challenger",
            price_cents=1_250,
            observed_at=cutoff - timedelta(days=6),
        ),
        evaluation_metrics={"baselineReleaseId": str(incumbent.id)},
    )
    active = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="active-challenger",
        code_revision="active-code",
        training_data_revision="active-training",
        parameters_or_artifact=_model_artifact(
            release_id="active-challenger",
            price_cents=1_500,
            observed_at=cutoff - timedelta(days=5),
        ),
        evaluation_metrics={"baselineReleaseId": str(incumbent.id)},
    )
    stale_baseline = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="stale-baseline-challenger",
        code_revision="stale-code",
        training_data_revision="stale-training",
        parameters_or_artifact=_model_artifact(
            release_id="stale-baseline-challenger",
            price_cents=2_000,
            observed_at=cutoff - timedelta(days=5),
        ),
        evaluation_metrics={"baselineReleaseId": str(retired_incumbent.id)},
    )
    retired_challenger = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="retired-challenger",
        code_revision="retired-challenger-code",
        training_data_revision="retired-challenger-training",
        parameters_or_artifact=_model_artifact(
            release_id="retired-challenger",
            price_cents=2_500,
            observed_at=cutoff - timedelta(days=8),
        ),
        evaluation_metrics={"baselineReleaseId": str(retired_incumbent.id)},
        promoted_at=cutoff - timedelta(days=7),
        retired_at=cutoff - timedelta(days=6),
    )

    created = evaluate_non_authoritative_releases(knowledge_cutoff=cutoff)

    assert created == 1
    assert list(ShadowCoverPrediction.objects.values_list("venue_id", "model_release_id")) == [
        (venue.id, active.id)
    ]
    assert not ShadowCoverPrediction.objects.filter(
        model_release__in=(
            retired_incumbent,
            superseded_active,
            stale_baseline,
            retired_challenger,
        )
    ).exists()


@pytest.mark.django_db
@override_settings(CODE_REVISION="recovery-command-code")
def test_issue_cover_model_recovery_registers_a_new_behavioral_clone():
    now = timezone.now().replace(second=0, microsecond=0)
    source_cutoff = now - timedelta(days=20)
    source_revision = CoverTrainingRevision.objects.create(
        data_revision="recovery-source-training",
        knowledge_cutoff=source_cutoff,
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    source = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="retired-known-good",
        code_revision="retired-code",
        training_data_revision=source_revision.data_revision,
        parameters_or_artifact=_model_artifact(
            release_id="retired-known-good",
            price_cents=1_500,
            observed_at=source_cutoff - timedelta(days=1),
        ),
        promoted_at=source_cutoff,
        retired_at=source_cutoff + timedelta(days=5),
    )
    incumbent = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="current-incumbent",
        code_revision="current-code",
        training_data_revision="current-training",
        parameters_or_artifact=_model_artifact(
            release_id="current-incumbent",
            price_cents=2_500,
            observed_at=now - timedelta(days=2),
        ),
        is_authoritative=True,
        promoted_at=now - timedelta(days=1),
    )

    call_command(
        "issue_cover_model_recovery",
        str(source.id),
        model_version="recovery-retired-known-good-v2",
        verbosity=0,
    )

    candidate = CoverModelRelease.objects.get(model_version="recovery-retired-known-good-v2")
    assert candidate.id != source.id
    assert candidate.model_kind == "historical_challenger"
    assert candidate.code_revision == "recovery-command-code"
    assert candidate.training_data_revision == source.training_data_revision
    assert candidate.is_authoritative is False
    assert candidate.promoted_at is None
    assert candidate.retired_at is None
    assert candidate.evaluation_metrics == {
        "status": "shadow_pending",
        "promotion": "explicit_only",
        "baselineReleaseId": str(incumbent.id),
        "recoverySourceReleaseId": str(source.id),
        "recoverySourceArtifactSha256": HistoricalModel.from_artifact(
            source.parameters_or_artifact
        ).artifact_sha256(),
    }
    source_model = HistoricalModel.from_artifact(source.parameters_or_artifact)
    candidate_model = HistoricalModel.from_artifact(candidate.parameters_or_artifact)
    target = now + timedelta(hours=1)
    source_prediction = source_model.predict("training-venue", target, now)
    candidate_prediction = candidate_model.predict("training-venue", target, now)
    assert source_prediction is not None
    assert candidate_prediction is not None
    assert candidate_prediction.point_cents == source_prediction.point_cents
    assert candidate_prediction.low_cents == source_prediction.low_cents
    assert candidate_prediction.high_cents == source_prediction.high_cents
    assert candidate_prediction.probabilities == source_prediction.probabilities
    assert candidate_prediction.model_release == "recovery-retired-known-good-v2"
    assert JobRun.objects.get(name="issue_cover_model_recovery").status == "succeeded"
    audit = AuditEvent.objects.get(kind="cover_model_recovery_issued")
    assert audit.target_reference == str(candidate.id)
    assert audit.metadata["sourceReleaseId"] == str(source.id)


@pytest.mark.django_db
def test_recovery_candidate_is_evaluated_after_both_release_training_cutoffs():
    cutoff = timezone.now().replace(second=0, microsecond=0)
    source_cutoff = cutoff - timedelta(days=40)
    incumbent_cutoff = cutoff - timedelta(days=10)
    source_revision = CoverTrainingRevision.objects.create(
        data_revision="older-recovery-training",
        knowledge_cutoff=source_cutoff,
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    incumbent_revision = CoverTrainingRevision.objects.create(
        data_revision="newer-incumbent-training",
        knowledge_cutoff=incumbent_cutoff,
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    source = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="older-known-good",
        code_revision="older-code",
        training_data_revision=source_revision.data_revision,
        parameters_or_artifact=_model_artifact(
            release_id="older-known-good",
            price_cents=1_500,
            observed_at=source_cutoff - timedelta(days=1),
        ),
        promoted_at=source_cutoff,
        retired_at=source_cutoff + timedelta(days=5),
    )
    incumbent = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="newer-incumbent",
        code_revision="newer-code",
        training_data_revision=incumbent_revision.data_revision,
        parameters_or_artifact=_model_artifact(
            release_id="newer-incumbent",
            price_cents=1_000,
            observed_at=incumbent_cutoff - timedelta(days=1),
        ),
        is_authoritative=True,
        promoted_at=incumbent_cutoff,
    )
    venues = [
        Venue.objects.create(slug=f"recovery-evaluation-{index}", name=f"Venue {index}")
        for index in range(4)
    ]
    for index in range(20):
        _held_out_report(
            venues[index % len(venues)],
            incumbent_cutoff + timedelta(days=index // 5 + 1),
            price_cents=1_500,
        )
    call_command(
        "issue_cover_model_recovery",
        str(source.id),
        model_version="recovery-after-newer-incumbent",
        verbosity=0,
    )
    candidate = CoverModelRelease.objects.get(model_version="recovery-after-newer-incumbent")

    call_command(
        "evaluate_cover_challenger",
        str(candidate.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )

    receipt = CoverModelEvaluationReceipt.objects.get(challenger=candidate)
    assert receipt.incumbent == incumbent
    assert receipt.evaluation_start == incumbent_cutoff
    assert receipt.metrics["sample"]["common_observations"] == 20
    assert receipt.promotion_eligible is True
    assert evaluation_receipt_is_valid(receipt)


@pytest.mark.django_db
def test_evaluate_cover_challenger_writes_one_immutable_winning_receipt():
    cutoff, training_revision, incumbent, challenger = _winning_evaluation_setup()

    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )

    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    assert receipt.incumbent == incumbent
    assert receipt.challenger_training_revision == training_revision
    assert receipt.protocol_version == "chronological_holdout_v1"
    assert receipt.metrics["sample"] == {
        "common_observations": 20,
        "service_nights": 4,
        "venues": 4,
    }
    assert receipt.challenger_won is True
    assert receipt.promotion_eligible is True
    assert len(receipt.row_selection_sha256) == 64
    assert len(receipt.receipt_sha256) == 64
    assert JobRun.objects.get(name="evaluate_cover_challenger").status == "succeeded"
    assert AuditEvent.objects.get(kind="cover_model_evaluated").target_reference == str(
        challenger.id
    )
    receipt.metrics = {"tampered": True}
    with pytest.raises(ValidationError, match="immutable"):
        receipt.save()


@pytest.mark.django_db
def test_evaluate_cover_challenger_replays_idempotently_for_one_frozen_revision():
    cutoff, _training_revision, _incumbent, challenger = _winning_evaluation_setup()

    for _attempt in range(2):
        call_command(
            "evaluate_cover_challenger",
            str(challenger.id),
            cutoff=cutoff.isoformat(),
            verbosity=0,
        )

    assert CoverModelEvaluationReceipt.objects.filter(challenger=challenger).count() == 1
    assert JobRun.objects.filter(name="evaluate_cover_challenger", status="succeeded").count() == 2
    assert (
        JobRun.objects.filter(
            name="evaluate_cover_challenger",
            result_summary__created=False,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_evaluation_receipt_hash_survives_non_utc_input_and_database_reload():
    cutoff, _training_revision, _incumbent, challenger = _winning_evaluation_setup()
    central_cutoff = cutoff.astimezone(datetime_timezone(timedelta(hours=-5)))

    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=central_cutoff.isoformat(),
        verbosity=0,
    )

    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    assert receipt.evaluation_cutoff.tzinfo is UTC
    assert evaluation_receipt_is_valid(receipt)


@pytest.mark.django_db
def test_evaluation_consumes_the_exact_rows_captured_by_its_data_revision():
    cutoff, training_revision, _incumbent, challenger = _winning_evaluation_setup()
    venue = Venue.objects.order_by("slug").first()
    assert venue is not None
    inserted_after_capture: list[bool] = []

    def insert_holdout_row_after_revision_is_named(sender, instance, created, **_kwargs):
        if created and instance.data_revision.startswith("production:"):
            _held_out_report(
                venue,
                training_revision.knowledge_cutoff + timedelta(days=5),
            )
            inserted_after_capture.append(True)

    post_save.connect(
        insert_holdout_row_after_revision_is_named,
        sender=CoverTrainingRevision,
        dispatch_uid="test-captured-cover-evaluation-selection",
        weak=False,
    )
    try:
        call_command(
            "evaluate_cover_challenger",
            str(challenger.id),
            cutoff=cutoff.isoformat(),
            verbosity=0,
        )
    finally:
        post_save.disconnect(
            sender=CoverTrainingRevision,
            dispatch_uid="test-captured-cover-evaluation-selection",
        )

    assert inserted_after_capture == [True]
    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    assert receipt.evaluation_data_revision.observations_admitted == 20
    assert receipt.metrics["sample"]["common_observations"] == 20


@pytest.mark.django_db
def test_evaluate_cover_challenger_fails_closed_below_holdout_policy():
    cutoff, _training_revision, _incumbent, challenger = _winning_evaluation_setup()
    last_night = list(Submission.objects.order_by("-observed_at_client")[:5])
    assert len(last_night) == 5
    CoverObservation.objects.filter(submission__in=last_night).delete()
    Submission.objects.filter(pk__in=[submission.pk for submission in last_night]).delete()

    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )

    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    assert receipt.metrics["sample"]["common_observations"] == 15
    assert receipt.metrics["sample"]["service_nights"] == 3
    assert receipt.gates["minimum_common_observations"] is False
    assert receipt.gates["minimum_service_nights"] is False
    assert receipt.challenger_won is True
    assert receipt.promotion_eligible is False
    with pytest.raises(CommandError, match="ineligible"):
        call_command(
            "promote_cover_model",
            str(challenger.id),
            evaluation_receipt=str(receipt.id),
            verbosity=0,
        )


@pytest.mark.django_db
def test_evaluate_cover_challenger_rejects_training_artifact_with_holdout_data():
    cutoff, training_revision, _incumbent, challenger = _winning_evaluation_setup()
    artifact = dict(challenger.parameters_or_artifact)
    observations = [dict(value) for value in artifact["observations"]]
    observations[0]["available_at"] = (
        training_revision.knowledge_cutoff + timedelta(seconds=1)
    ).isoformat()
    artifact["observations"] = observations
    CoverModelRelease.objects.filter(pk=challenger.pk).update(parameters_or_artifact=artifact)

    with pytest.raises(CommandError, match="holdout data"):
        call_command(
            "evaluate_cover_challenger",
            str(challenger.id),
            cutoff=cutoff.isoformat(),
            verbosity=0,
        )

    assert CoverModelEvaluationReceipt.objects.count() == 0
    assert JobRun.objects.get(name="evaluate_cover_challenger").status == "failed"


@pytest.mark.django_db
def test_evaluate_cover_challenger_rejects_a_future_knowledge_cutoff():
    cutoff, _training_revision, _incumbent, challenger = _winning_evaluation_setup()

    with pytest.raises(CommandError, match="future"):
        call_command(
            "evaluate_cover_challenger",
            str(challenger.id),
            cutoff=(cutoff + timedelta(days=1)).isoformat(),
            verbosity=0,
        )

    assert CoverModelEvaluationReceipt.objects.count() == 0


@pytest.mark.django_db
def test_promote_cover_model_requires_and_accepts_the_exact_winning_receipt():
    cutoff, _training_revision, incumbent, challenger = _winning_evaluation_setup()
    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )
    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)

    call_command(
        "promote_cover_model",
        str(challenger.id),
        evaluation_receipt=str(receipt.id),
        verbosity=0,
    )

    incumbent.refresh_from_db()
    challenger.refresh_from_db()
    assert incumbent.is_authoritative is False
    assert challenger.is_authoritative is True
    assert JobRun.objects.get(name="promote_cover_model").status == "succeeded"
    assert AuditEvent.objects.get(kind="cover_model_promoted").metadata[
        "evaluationReceiptId"
    ] == str(receipt.id)


@pytest.mark.django_db
def test_promote_cover_model_rejects_an_artifact_changed_after_evaluation():
    cutoff, _training_revision, _incumbent, challenger = _winning_evaluation_setup()
    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )
    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    changed = _model_artifact(
        release_id="challenger",
        price_cents=2_000,
        observed_at=cutoff - timedelta(days=20),
    )
    CoverModelRelease.objects.filter(pk=challenger.pk).update(parameters_or_artifact=changed)

    with pytest.raises(CommandError, match="artifacts"):
        call_command(
            "promote_cover_model",
            str(challenger.id),
            evaluation_receipt=str(receipt.id),
            verbosity=0,
        )

    challenger.refresh_from_db()
    assert challenger.is_authoritative is False


@pytest.mark.django_db
def test_promote_cover_model_rejects_receipt_after_authority_changes():
    cutoff, _training_revision, incumbent, challenger = _winning_evaluation_setup()
    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )
    receipt = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    incumbent.is_authoritative = False
    incumbent.save(update_fields=["is_authoritative"])
    replacement = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="replacement-incumbent",
        code_revision="replacement-code",
        training_data_revision="replacement-training",
        parameters_or_artifact=_model_artifact(
            release_id="replacement-incumbent",
            price_cents=1_000,
            observed_at=cutoff - timedelta(days=20),
        ),
        is_authoritative=True,
    )

    with pytest.raises(CommandError, match="stale"):
        call_command(
            "promote_cover_model",
            str(challenger.id),
            evaluation_receipt=str(receipt.id),
            verbosity=0,
        )

    challenger.refresh_from_db()
    replacement.refresh_from_db()
    assert challenger.is_authoritative is False
    assert replacement.is_authoritative is True


@pytest.mark.django_db
def test_promote_cover_model_rejects_an_older_win_after_a_newer_loss():
    cutoff, training_revision, _incumbent, challenger = _winning_evaluation_setup()
    first_cutoff = training_revision.knowledge_cutoff + timedelta(days=5)
    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=first_cutoff.isoformat(),
        verbosity=0,
    )
    older_win = CoverModelEvaluationReceipt.objects.get(challenger=challenger)
    assert older_win.promotion_eligible is True

    venues = list(Venue.objects.order_by("slug"))
    for index in range(20):
        _held_out_report(
            venues[index % len(venues)],
            first_cutoff + timedelta(days=index // 5 + 1),
            price_cents=1_000,
        )
    call_command(
        "evaluate_cover_challenger",
        str(challenger.id),
        cutoff=cutoff.isoformat(),
        verbosity=0,
    )
    newer_loss = CoverModelEvaluationReceipt.objects.exclude(pk=older_win.pk).get()
    assert newer_loss.promotion_eligible is False

    with pytest.raises(CommandError, match="stale"):
        call_command(
            "promote_cover_model",
            str(challenger.id),
            evaluation_receipt=str(older_win.id),
            verbosity=0,
        )

    challenger.refresh_from_db()
    assert challenger.is_authoritative is False
