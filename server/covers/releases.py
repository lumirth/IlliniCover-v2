import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from covers.modeling import (
    AdmissionClass,
    HistoricalModel,
    HistoricalModelConfig,
    HistoricalObservation,
    ObservationInput,
    assess_observation,
)
from covers.modeling.evaluation import (
    DEFAULT_CHALLENGER_PROMOTION_POLICY,
    compare_historical_models,
)
from covers.modeling.receipts import JsonValue, canonical_receipt_hash
from covers.modeling.types import EvidenceAssessment
from covers.models import (
    CoverModelEvaluationReceipt,
    CoverModelRelease,
    CoverObservation,
    CoverTrainingRevision,
    ShadowCoverPrediction,
)
from covers.services import observation_input, service_date_for


class ChallengerEvaluationError(ValueError):
    pass


def _utc_timestamp(value: datetime) -> str:
    """Canonicalize an aware receipt timestamp independent of input offset/storage."""

    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class FrozenTrainingSelection:
    revision: CoverTrainingRevision
    rows: tuple[HistoricalObservation, ...]
    row_receipts: tuple[dict[str, object], ...]


@transaction.atomic
def build_and_promote_initial_release() -> CoverModelRelease:
    evaluation_path = (
        settings.REPOSITORY_DIR / "docs" / "model" / "cover-historical-v1-evaluation.json"
    )
    if not evaluation_path.exists():
        evaluation_path = (
            settings.REPOSITORY_DIR
            / "data"
            / "cover"
            / "recovered-cover-v1"
            / "model-selection-receipt.json"
        )
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    training_revision = evaluation["dataset"]["sha256"]
    existing = CoverModelRelease.objects.filter(
        model_kind="historical",
        model_version="cover_historical_v1",
    ).first()
    if existing is not None:
        current = CoverModelRelease.objects.filter(is_authoritative=True).first()
        if current is not None:
            return current
        return promote_release(existing)
    records = []
    observations = (
        CoverObservation.objects.filter(submission__source_kind="dataset_import")
        .select_related("submission")
        .order_by("submission__received_at_server", "submission_id")
    )
    for observation in observations:
        submission = observation.submission
        records.append(
            HistoricalObservation(
                observation_id=str(submission.id),
                venue_id=str(submission.venue_id),
                observed_at=submission.observed_at_client,
                available_at=submission.received_at_server,
                service_date=service_date_for(submission.observed_at_client),
                price_cents=observation.reported_price_cents,
            )
        )
    model = HistoricalModel.fit(
        records,
        HistoricalModelConfig(release_id="cover_historical_v1"),
    )
    revision, _ = CoverTrainingRevision.objects.get_or_create(
        data_revision=training_revision,
        defaults={
            "knowledge_cutoff": max(record.available_at for record in records),
            "service_nights": len({record.service_date for record in records}),
            "observations_seen": len(records),
            "observations_admitted": len(records),
            "provenance": {
                "dataset": evaluation["dataset"]["release"],
                "artifactSha256": training_revision,
            },
        },
    )
    release = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="cover_historical_v1",
        code_revision=settings.CODE_REVISION,
        training_data_revision=revision.data_revision,
        parameters_or_artifact=model.to_artifact(),
        evaluation_metrics=evaluation,
    )
    return promote_release(release)


@transaction.atomic
def promote_release(
    release: CoverModelRelease,
    *,
    evaluation_receipt: CoverModelEvaluationReceipt | None = None,
) -> CoverModelRelease:
    release = CoverModelRelease.objects.get(pk=release.pk)
    if release.is_authoritative:
        return release
    if release.retired_at is not None:
        raise ChallengerEvaluationError("A retired cover model release cannot be promoted again")
    if release.model_kind == "historical_challenger" and release.promoted_at is None:
        validate_evaluation_receipt_for_promotion(release, evaluation_receipt)
    now = timezone.now()
    CoverModelRelease.objects.filter(is_authoritative=True).exclude(pk=release.pk).update(
        is_authoritative=False, retired_at=now
    )
    CoverModelRelease.objects.filter(pk=release.pk).update(
        is_authoritative=True, promoted_at=now, retired_at=None
    )
    release.refresh_from_db()
    return release


@transaction.atomic
def capture_completed_training_rows(*, knowledge_cutoff=None) -> FrozenTrainingSelection:
    """Name and return one exact completed-night row selection."""

    knowledge_cutoff = (knowledge_cutoff or timezone.now()).astimezone(UTC)
    observations_seen, admitted, receipts = completed_training_selection(knowledge_cutoff)
    canonical = json.dumps(receipts, sort_keys=True, separators=(",", ":"))
    data_revision = f"production:{hashlib.sha256(canonical.encode()).hexdigest()}"
    revision, _ = CoverTrainingRevision.objects.get_or_create(
        data_revision=data_revision,
        defaults={
            "knowledge_cutoff": knowledge_cutoff,
            "service_nights": len({row.service_date for row in admitted}),
            "observations_seen": observations_seen,
            "observations_admitted": len(admitted),
            "provenance": {
                "kind": "production_completed_nights",
                "selectionVersion": "cover_training_admission_v1",
                "rowsSha256": hashlib.sha256(canonical.encode()).hexdigest(),
            },
        },
    )
    return FrozenTrainingSelection(
        revision=revision,
        rows=tuple(admitted),
        row_receipts=tuple(receipts),
    )


def snapshot_completed_training_rows(*, knowledge_cutoff=None) -> CoverTrainingRevision:
    """Persist the immutable name and counts for one captured training selection."""

    return capture_completed_training_rows(knowledge_cutoff=knowledge_cutoff).revision


@transaction.atomic
def train_completed_night_challenger(
    *,
    knowledge_cutoff=None,
    frozen_selection: FrozenTrainingSelection | None = None,
) -> CoverModelRelease | None:
    """Fit one immutable production challenger; never auto-promote it."""

    if frozen_selection is None:
        frozen_selection = capture_completed_training_rows(
            knowledge_cutoff=knowledge_cutoff or timezone.now()
        )
    elif (
        knowledge_cutoff is not None
        and knowledge_cutoff != frozen_selection.revision.knowledge_cutoff
    ):
        raise ChallengerEvaluationError(
            "The training cutoff does not match the frozen training selection"
        )
    revision = frozen_selection.revision
    knowledge_cutoff = revision.knowledge_cutoff
    rows = frozen_selection.rows
    if not rows:
        return None
    baseline = CoverModelRelease.objects.filter(is_authoritative=True).first()
    if baseline is None:
        raise ChallengerEvaluationError(
            "An authoritative baseline is required before training a challenger"
        )
    identity = {
        "identityVersion": "cover_challenger_release_v1",
        "trainingDataRevision": revision.data_revision,
        "codeRevision": settings.CODE_REVISION,
        "baselineReleaseId": str(baseline.id),
    }
    release_id = f"production_{canonical_receipt_hash(cast(JsonValue, identity))[:24]}"
    model = HistoricalModel.fit(rows, HistoricalModelConfig(release_id=release_id))
    artifact = model.to_artifact()
    evaluation_metrics = {
        "status": "shadow_pending",
        "promotion": "explicit_only",
        "observations": len(rows),
        "knowledgeCutoff": _utc_timestamp(knowledge_cutoff),
        "baselineReleaseId": str(baseline.id),
    }
    release, created = CoverModelRelease.objects.get_or_create(
        model_kind="historical_challenger",
        model_version=release_id,
        defaults={
            "code_revision": settings.CODE_REVISION,
            "training_data_revision": revision.data_revision,
            "parameters_or_artifact": artifact,
            "evaluation_metrics": evaluation_metrics,
        },
    )
    if not created and (
        release.code_revision != settings.CODE_REVISION
        or release.training_data_revision != revision.data_revision
        or release.context_feature_revision
        or release.parameters_or_artifact != artifact
        or release.evaluation_metrics != evaluation_metrics
    ):
        raise ChallengerEvaluationError(
            "The existing challenger identity does not match its immutable payload"
        )
    if created:
        CoverModelRelease.objects.filter(
            model_kind="historical_challenger",
            is_authoritative=False,
            promoted_at__isnull=True,
            retired_at__isnull=True,
        ).exclude(pk=release.pk).update(retired_at=timezone.now())
    return release


@transaction.atomic
def issue_recovery_release(
    source: CoverModelRelease,
    *,
    model_version: str,
) -> tuple[CoverModelRelease, bool]:
    """Register a fresh candidate that reproduces one retired release's behavior."""

    if not model_version or len(model_version) > 80:
        raise ChallengerEvaluationError("The recovery model version must be 1 to 80 characters")
    source = CoverModelRelease.objects.get(pk=source.pk)
    if source.retired_at is None:
        raise ChallengerEvaluationError("A recovery source must be a retired cover model release")
    if source.model_kind not in {"historical", "historical_challenger"}:
        raise ChallengerEvaluationError("A recovery source must be a historical cover model")
    if not CoverTrainingRevision.objects.filter(
        data_revision=source.training_data_revision
    ).exists():
        raise ChallengerEvaluationError("The recovery source training revision is unavailable")
    incumbent = CoverModelRelease.objects.filter(is_authoritative=True).first()
    if incumbent is None:
        raise ChallengerEvaluationError(
            "An authoritative incumbent is required before issuing recovery"
        )
    try:
        source_model = HistoricalModel.from_artifact(source.parameters_or_artifact)
    except (KeyError, TypeError, ValueError) as error:
        raise ChallengerEvaluationError("The recovery source artifact is invalid") from error

    artifact = deepcopy(source.parameters_or_artifact)
    config = artifact.get("config")
    if not isinstance(config, dict):
        raise ChallengerEvaluationError("The recovery source artifact is invalid")
    config["release_id"] = model_version
    try:
        HistoricalModel.from_artifact(artifact)
    except (KeyError, TypeError, ValueError) as error:
        raise ChallengerEvaluationError("The recovery candidate artifact is invalid") from error
    evaluation_metrics = {
        "status": "shadow_pending",
        "promotion": "explicit_only",
        "baselineReleaseId": str(incumbent.id),
        "recoverySourceReleaseId": str(source.id),
        "recoverySourceArtifactSha256": source_model.artifact_sha256(),
    }
    candidate, created = CoverModelRelease.objects.get_or_create(
        model_kind="historical_challenger",
        model_version=model_version,
        defaults={
            "code_revision": settings.CODE_REVISION,
            "training_data_revision": source.training_data_revision,
            "context_feature_revision": source.context_feature_revision,
            "parameters_or_artifact": artifact,
            "evaluation_metrics": evaluation_metrics,
        },
    )
    if not created and (
        candidate.code_revision != settings.CODE_REVISION
        or candidate.training_data_revision != source.training_data_revision
        or candidate.context_feature_revision != source.context_feature_revision
        or candidate.parameters_or_artifact != artifact
        or candidate.evaluation_metrics != evaluation_metrics
        or candidate.is_authoritative
        or candidate.promoted_at is not None
        or candidate.retired_at is not None
    ):
        raise ChallengerEvaluationError(
            "The existing recovery identity does not match its immutable payload"
        )
    if created:
        CoverModelRelease.objects.filter(
            model_kind="historical_challenger",
            is_authoritative=False,
            promoted_at__isnull=True,
            retired_at__isnull=True,
        ).exclude(pk=candidate.pk).update(retired_at=timezone.now())
    return candidate, created


def completed_training_selection(
    knowledge_cutoff,
) -> tuple[int, list[HistoricalObservation], list[dict[str, object]]]:
    """Select exactly the weighted rows hashed into and fitted by a challenger."""

    active_service_date = service_date_for(knowledge_cutoff)
    observations = list(
        CoverObservation.objects.filter(
            submission__observed_at_client__lte=knowledge_cutoff,
            submission__received_at_server__lte=knowledge_cutoff,
        )
        .exclude(submission__source_kind="dataset_import")
        .select_related(
            "submission",
            "submission__venue",
            "submission__private_context",
            "submission__private_context__actor",
        )
        .order_by("submission__received_at_server", "submission_id")
    )
    completed = [
        observation
        for observation in observations
        if service_date_for(observation.submission.observed_at_client) < active_service_date
    ]

    # One actor contributes at most its latest admissible label per venue and
    # service night. Assessment happens before deduplication so an excluded
    # abusive upload cannot erase an earlier valid observation.
    latest_by_actor: dict[tuple[str, date, str], tuple[ObservationInput, EvidenceAssessment]] = {}
    for observation in completed:
        model_input = observation_input(observation)
        assessment = assess_observation(model_input, knowledge_cutoff=knowledge_cutoff)
        if assessment.admission in {AdmissionClass.EXCLUDED, AdmissionClass.REJECTED}:
            continue
        key = (
            model_input.venue_id,
            service_date_for(model_input.observed_at),
            model_input.actor_independence_key,
        )
        latest_by_actor[key] = (model_input, assessment)

    independent_prices: set[tuple[str, date, int]] = set()
    echo_actors: dict[tuple[str, date, int], set[str]] = {}
    for model_input, assessment in latest_by_actor.values():
        price_key = (
            model_input.venue_id,
            service_date_for(model_input.observed_at),
            model_input.price_cents,
        )
        if assessment.independent_price_label:
            independent_prices.add(price_key)
        else:
            echo_actors.setdefault(price_key, set()).add(model_input.actor_independence_key)

    admitted_inputs = []
    for model_input, assessment in latest_by_actor.values():
        price_key = (
            model_input.venue_id,
            service_date_for(model_input.observed_at),
            model_input.price_cents,
        )
        if not assessment.independent_price_label and not (
            price_key in independent_prices or len(echo_actors.get(price_key, set())) >= 2
        ):
            continue
        admitted_inputs.append((model_input, assessment))
    admitted_inputs.sort(
        key=lambda item: (
            item[0].observed_at,
            item[0].received_at,
            item[0].observation_id,
        )
    )

    rows = [
        HistoricalObservation(
            observation_id=model_input.observation_id,
            venue_id=model_input.venue_id,
            observed_at=model_input.observed_at,
            available_at=model_input.received_at,
            service_date=service_date_for(model_input.observed_at),
            price_cents=model_input.price_cents,
            weight=assessment.weight,
        )
        for model_input, assessment in admitted_inputs
    ]
    receipts = [
        {
            "observationId": row.observation_id,
            "venueId": row.venue_id,
            "observedAt": row.observed_at.isoformat(),
            "availableAt": row.available_at.isoformat(),
            "serviceDate": row.service_date.isoformat(),
            "priceCents": row.price_cents,
            "weight": format(row.weight, ".12g"),
            "reasons": list(assessment.reasons),
        }
        for row, (_model_input, assessment) in zip(rows, admitted_inputs, strict=True)
    ]
    return len(completed), rows, receipts


@transaction.atomic
def evaluate_challenger(
    release: CoverModelRelease,
    *,
    evaluation_cutoff: datetime,
) -> tuple[CoverModelEvaluationReceipt, bool]:
    """Persist one deterministic head-to-head chronological evaluation receipt."""

    release = CoverModelRelease.objects.select_for_update().get(pk=release.pk)
    if timezone.is_naive(evaluation_cutoff):
        raise ChallengerEvaluationError("The evaluation cutoff must include a time zone")
    evaluation_cutoff = evaluation_cutoff.astimezone(UTC)
    if evaluation_cutoff > timezone.now():
        raise ChallengerEvaluationError("The evaluation cutoff cannot be in the future")
    if release.model_kind != "historical_challenger":
        raise ChallengerEvaluationError("Only a historical challenger can be evaluated")
    baseline_id = release.evaluation_metrics.get("baselineReleaseId")
    if not isinstance(baseline_id, str):
        raise ChallengerEvaluationError("The challenger has no immutable baseline release")
    incumbent = CoverModelRelease.objects.filter(pk=baseline_id).first()
    if incumbent is None or not incumbent.is_authoritative:
        raise ChallengerEvaluationError("The challenger baseline is no longer authoritative")
    training_revision = CoverTrainingRevision.objects.filter(
        data_revision=release.training_data_revision
    ).first()
    if training_revision is None:
        raise ChallengerEvaluationError("The challenger training revision is unavailable")
    incumbent_training_cutoff = _release_training_cutoff(incumbent)
    evaluation_start = max(
        training_revision.knowledge_cutoff.astimezone(UTC),
        incumbent_training_cutoff,
    )
    if evaluation_cutoff <= evaluation_start:
        raise ChallengerEvaluationError("The evaluation cutoff must follow both releases' training")

    try:
        challenger_model = HistoricalModel.from_artifact(release.parameters_or_artifact)
        incumbent_model = HistoricalModel.from_artifact(incumbent.parameters_or_artifact)
    except (KeyError, TypeError, ValueError) as error:
        raise ChallengerEvaluationError("A compared release artifact is invalid") from error
    _validate_artifact_cutoff(
        release.parameters_or_artifact,
        cutoff=training_revision.knowledge_cutoff,
    )
    _validate_artifact_cutoff(
        incumbent.parameters_or_artifact,
        cutoff=incumbent_training_cutoff,
    )

    evaluation_selection = capture_completed_training_rows(knowledge_cutoff=evaluation_cutoff)
    evaluation_revision = evaluation_selection.revision
    effective_cutoff = evaluation_revision.knowledge_cutoff
    if effective_cutoff <= evaluation_start:
        raise ChallengerEvaluationError("No newer frozen evaluation revision is available")
    selected = [
        (row, receipt)
        for row, receipt in zip(
            evaluation_selection.rows,
            evaluation_selection.row_receipts,
            strict=True,
        )
        if row.observed_at > evaluation_start and row.available_at > evaluation_start
    ]
    selected_rows = tuple(row for row, _receipt in selected)
    selected_receipts = [receipt for _row, receipt in selected]
    row_selection_sha256 = canonical_receipt_hash(cast(JsonValue, selected_receipts))
    comparison = compare_historical_models(
        incumbent_model,
        challenger_model,
        selected_rows,
        policy=DEFAULT_CHALLENGER_PROMOTION_POLICY,
    )
    metrics = {
        key: comparison[key]
        for key in ("policy", "sample", "incumbent", "challenger", "comparison")
    }
    gates = cast(dict[str, bool], comparison["gates"])
    not_evaluable = cast(dict[str, str], comparison["not_evaluable_dimensions"])
    challenger_won = bool(comparison["challenger_won"])
    promotion_eligible = bool(comparison["promotion_eligible"])
    challenger_artifact_sha256 = challenger_model.artifact_sha256()
    incumbent_artifact_sha256 = incumbent_model.artifact_sha256()
    receipt_values = {
        "protocolVersion": DEFAULT_CHALLENGER_PROMOTION_POLICY.protocol_version,
        "challengerReleaseId": str(release.id),
        "incumbentReleaseId": str(incumbent.id),
        "challengerTrainingRevision": training_revision.data_revision,
        "evaluationDataRevision": evaluation_revision.data_revision,
        "evaluatorCodeRevision": settings.CODE_REVISION,
        "evaluationStart": _utc_timestamp(evaluation_start),
        "evaluationCutoff": _utc_timestamp(effective_cutoff),
        "challengerArtifactSha256": challenger_artifact_sha256,
        "incumbentArtifactSha256": incumbent_artifact_sha256,
        "rowSelectionSha256": row_selection_sha256,
        "metrics": metrics,
        "gates": gates,
        "notEvaluableDimensions": not_evaluable,
        "challengerWon": challenger_won,
        "promotionEligible": promotion_eligible,
    }
    receipt_sha256 = canonical_receipt_hash(cast(JsonValue, receipt_values))
    receipt, created = CoverModelEvaluationReceipt.objects.get_or_create(
        protocol_version=DEFAULT_CHALLENGER_PROMOTION_POLICY.protocol_version,
        challenger=release,
        incumbent=incumbent,
        evaluation_data_revision=evaluation_revision,
        defaults={
            "challenger_training_revision": training_revision,
            "evaluator_code_revision": settings.CODE_REVISION,
            "evaluation_start": evaluation_start,
            "evaluation_cutoff": effective_cutoff,
            "challenger_artifact_sha256": challenger_artifact_sha256,
            "incumbent_artifact_sha256": incumbent_artifact_sha256,
            "row_selection_sha256": row_selection_sha256,
            "metrics": metrics,
            "gates": gates,
            "not_evaluable_dimensions": not_evaluable,
            "challenger_won": challenger_won,
            "promotion_eligible": promotion_eligible,
            "receipt_sha256": receipt_sha256,
        },
    )
    if not evaluation_receipt_is_valid(receipt):
        raise ChallengerEvaluationError("The stored evaluation receipt failed validation")
    return receipt, created


def evaluation_receipt_is_valid(receipt: CoverModelEvaluationReceipt) -> bool:
    values = {
        "protocolVersion": receipt.protocol_version,
        "challengerReleaseId": str(receipt.challenger_id),
        "incumbentReleaseId": str(receipt.incumbent_id),
        "challengerTrainingRevision": receipt.challenger_training_revision.data_revision,
        "evaluationDataRevision": receipt.evaluation_data_revision.data_revision,
        "evaluatorCodeRevision": receipt.evaluator_code_revision,
        "evaluationStart": _utc_timestamp(receipt.evaluation_start),
        "evaluationCutoff": _utc_timestamp(receipt.evaluation_cutoff),
        "challengerArtifactSha256": receipt.challenger_artifact_sha256,
        "incumbentArtifactSha256": receipt.incumbent_artifact_sha256,
        "rowSelectionSha256": receipt.row_selection_sha256,
        "metrics": receipt.metrics,
        "gates": receipt.gates,
        "notEvaluableDimensions": receipt.not_evaluable_dimensions,
        "challengerWon": receipt.challenger_won,
        "promotionEligible": receipt.promotion_eligible,
    }
    return receipt.receipt_sha256 == canonical_receipt_hash(cast(JsonValue, values))


def validate_evaluation_receipt_for_promotion(
    release: CoverModelRelease,
    receipt: CoverModelEvaluationReceipt | None,
) -> None:
    if receipt is None:
        raise ChallengerEvaluationError(
            "An unpromoted challenger requires an immutable chronological winning "
            "evaluation receipt"
        )
    current = CoverModelRelease.objects.filter(is_authoritative=True).first()
    expected_gate_names = {
        "minimum_service_nights",
        "minimum_common_observations",
        "mae_strictly_improved",
        "zero_brier_non_regression",
        "high_cover_brier_non_regression",
        "interval_score_non_regression",
        "absolute_mae",
        "absolute_interval_coverage",
        "absolute_interval_width",
        "absolute_venue_mae",
    }
    latest_receipt_id = (
        CoverModelEvaluationReceipt.objects.filter(
            protocol_version=DEFAULT_CHALLENGER_PROMOTION_POLICY.protocol_version,
            challenger=release,
            incumbent=current,
        )
        .order_by("-evaluation_cutoff", "-created_at", "-id")
        .values_list("id", flat=True)
        .first()
        if current is not None
        else None
    )
    if (
        receipt.protocol_version != DEFAULT_CHALLENGER_PROMOTION_POLICY.protocol_version
        or receipt.challenger_id != release.id
        or current is None
        or receipt.incumbent_id != current.id
        or receipt.id != latest_receipt_id
        or not receipt.challenger_won
        or not receipt.promotion_eligible
        or not isinstance(receipt.metrics, dict)
        or receipt.metrics.get("policy") != asdict(DEFAULT_CHALLENGER_PROMOTION_POLICY)
        or not isinstance(receipt.gates, dict)
        or set(receipt.gates) != expected_gate_names
        or any(value is not True for value in receipt.gates.values())
        or not evaluation_receipt_is_valid(receipt)
    ):
        raise ChallengerEvaluationError("The evaluation receipt is stale, ineligible, or invalid")
    challenger = HistoricalModel.from_artifact(release.parameters_or_artifact)
    incumbent = HistoricalModel.from_artifact(current.parameters_or_artifact)
    if (
        receipt.challenger_training_revision.data_revision != release.training_data_revision
        or receipt.challenger_artifact_sha256 != challenger.artifact_sha256()
        or receipt.incumbent_artifact_sha256 != incumbent.artifact_sha256()
    ):
        raise ChallengerEvaluationError(
            "The evaluation receipt does not match the compared release artifacts"
        )


def _validate_artifact_cutoff(artifact, *, cutoff: datetime) -> None:
    rows = artifact.get("observations")
    if not isinstance(rows, list):
        raise ChallengerEvaluationError("A compared release artifact has no training rows")
    for row in rows:
        if not isinstance(row, dict):
            raise ChallengerEvaluationError("A compared release artifact row is invalid")
        try:
            observed_at = datetime.fromisoformat(str(row["observed_at"]))
            available_at = datetime.fromisoformat(str(row["available_at"]))
        except (KeyError, ValueError) as error:
            raise ChallengerEvaluationError("A compared release artifact row is invalid") from error
        if timezone.is_naive(observed_at) or timezone.is_naive(available_at):
            raise ChallengerEvaluationError("A compared release artifact row has no time zone")
        if observed_at > cutoff or available_at > cutoff:
            raise ChallengerEvaluationError("A compared release artifact contains holdout data")


def _release_training_cutoff(release: CoverModelRelease) -> datetime:
    revision = CoverTrainingRevision.objects.filter(
        data_revision=release.training_data_revision
    ).first()
    if revision is not None:
        return revision.knowledge_cutoff.astimezone(UTC)
    rows = release.parameters_or_artifact.get("observations")
    if not isinstance(rows, list):
        raise ChallengerEvaluationError("A compared release artifact has no training rows")
    timestamps: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ChallengerEvaluationError("A compared release artifact row is invalid")
        try:
            timestamps.extend(
                (
                    datetime.fromisoformat(str(row["observed_at"])),
                    datetime.fromisoformat(str(row["available_at"])),
                )
            )
        except (KeyError, ValueError) as error:
            raise ChallengerEvaluationError("A compared release artifact row is invalid") from error
    if any(timezone.is_naive(value) for value in timestamps):
        raise ChallengerEvaluationError("A compared release artifact row has no time zone")
    return max(
        (value.astimezone(UTC) for value in timestamps),
        default=datetime.min.replace(tzinfo=UTC),
    )


@transaction.atomic
def evaluate_non_authoritative_releases(*, knowledge_cutoff=None) -> int:
    """Persist shadow outputs; promotion remains an explicit Admin/ops action."""

    from venues.models import Venue

    from covers.modeling import HistoricalModel

    knowledge_cutoff = knowledge_cutoff or timezone.now()
    target_time = knowledge_cutoff
    created = 0
    incumbent_id = (
        CoverModelRelease.objects.filter(is_authoritative=True).values_list("id", flat=True).first()
    )
    if incumbent_id is None:
        return 0
    challengers = CoverModelRelease.objects.filter(
        model_kind="historical_challenger",
        is_authoritative=False,
        promoted_at__isnull=True,
        retired_at__isnull=True,
        evaluation_metrics__baselineReleaseId=str(incumbent_id),
    ).order_by("-created_at", "-id")[:1]
    for release in challengers:
        artifact = release.parameters_or_artifact
        if not artifact.get("artifact_schema"):
            continue
        model = HistoricalModel.from_artifact(artifact)
        for venue in Venue.objects.filter(is_active=True):
            prediction = model.predict(str(venue.id), target_time, knowledge_cutoff)
            _, was_created = ShadowCoverPrediction.objects.get_or_create(
                venue=venue,
                model_release=release,
                target_time=target_time,
                knowledge_cutoff=knowledge_cutoff,
                defaults={
                    "result_price_cents": prediction.point_cents if prediction else None,
                    "result_low_cents": prediction.low_cents if prediction else None,
                    "result_high_cents": prediction.high_cents if prediction else None,
                },
            )
            created += int(was_created)
    return created
