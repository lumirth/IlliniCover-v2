import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from submissions.models import Submission
from venues.models import Venue


class CoverObservation(models.Model):
    class InteractionKind(models.TextChoices):
        CONFIRM = "confirm", "Confirm"
        CORRECT = "correct", "Correct"
        DIRECT = "direct", "Direct"
        QUICK_CONFIRM = "quick_confirm", "Quick confirm"
        MANUAL = "manual", "Manual"

    submission = models.OneToOneField(
        Submission, on_delete=models.PROTECT, related_name="cover_observation"
    )
    reported_price_cents = models.PositiveIntegerField()
    interaction_kind = models.CharField(max_length=24, choices=InteractionKind.choices)
    displayed_decision = models.ForeignKey(
        "CoverDecision",
        on_delete=models.SET_NULL,
        related_name="confirming_observations",
        null=True,
        blank=True,
    )
    displayed_source = models.CharField(max_length=24, blank=True)
    displayed_price_kind = models.CharField(max_length=16, blank=True)
    displayed_price_cents = models.PositiveIntegerField(null=True, blank=True)
    displayed_price_low_cents = models.PositiveIntegerField(null=True, blank=True)
    displayed_price_high_cents = models.PositiveIntegerField(null=True, blank=True)
    price_prefilled = models.BooleanField(default=False)
    price_touched = models.BooleanField(default=False)
    source_dataset = models.CharField(max_length=120, blank=True)
    # Legacy random receipt retained for migration compatibility. Erasure must
    # never promote this per-observation value into independence: that would
    # turn one erased actor into many apparent contributors.
    deidentified_independence_key = models.UUIDField(default=uuid.uuid4, editable=False)
    independence_group_key = models.UUIDField(default=uuid.uuid4, editable=False)
    admission_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class CoverModelRelease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_kind = models.CharField(max_length=80)
    model_version = models.CharField(max_length=80)
    code_revision = models.CharField(max_length=80)
    training_data_revision = models.CharField(max_length=160)
    context_feature_revision = models.CharField(max_length=160, blank=True)
    parameters_or_artifact = models.JSONField(default=dict)
    evaluation_metrics = models.JSONField(default=dict)
    is_authoritative = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("model_kind", "model_version"), name="unique_cover_model_version"
            ),
            models.UniqueConstraint(
                fields=("is_authoritative",),
                condition=Q(is_authoritative=True),
                name="one_authoritative_cover_model",
            ),
        ]

    IMMUTABLE_FIELDS = (
        "model_kind",
        "model_version",
        "code_revision",
        "training_data_revision",
        "context_feature_revision",
        "parameters_or_artifact",
        "evaluation_metrics",
        "created_at",
    )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Model release artifacts and receipts are immutable")
        return super().save(*args, **kwargs)


class CoverDecision(models.Model):
    class PriceKind(models.TextChoices):
        SINGLE = "single", "Single"
        RANGE = "range", "Range"
        UNAVAILABLE = "unavailable", "Unavailable"

    class Source(models.TextChoices):
        LIVE = "live", "Live"
        ADVERTISED = "advertised", "Advertised"
        HISTORICAL = "historical", "Historical"
        MIXED = "mixed", "Mixed"
        UNCONFIRMED = "unconfirmed", "Unconfirmed"
        UNAVAILABLE = "unavailable", "Unavailable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="cover_decisions")
    target_time = models.DateTimeField()
    knowledge_cutoff = models.DateTimeField()
    computed_at = models.DateTimeField(auto_now_add=True)
    result_price_kind = models.CharField(max_length=16, choices=PriceKind.choices)
    result_price_cents = models.PositiveIntegerField(null=True, blank=True)
    result_low_cents = models.PositiveIntegerField(null=True, blank=True)
    result_high_cents = models.PositiveIntegerField(null=True, blank=True)
    source = models.CharField(max_length=24, choices=Source.choices)
    status = models.CharField(max_length=24)
    model_release = models.ForeignKey(
        CoverModelRelease,
        on_delete=models.PROTECT,
        related_name="decisions",
        null=True,
        blank=True,
    )
    evidence_revision = models.CharField(max_length=80)
    served_state_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    context_revision = models.CharField(max_length=80, blank=True)
    resolver_version = models.CharField(max_length=80)
    same_night_adjustment_summary = models.JSONField(default=dict)
    campus_adjustment_summary = models.JSONField(default=dict)

    class Meta:
        ordering = ("-computed_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("venue", "target_time", "knowledge_cutoff", "evidence_revision"),
                name="unique_exact_cover_decision_receipt",
            ),
            models.CheckConstraint(
                condition=(
                    Q(result_price_kind="single", result_price_cents__isnull=False)
                    | Q(
                        result_price_kind="range",
                        result_low_cents__isnull=False,
                        result_high_cents__isnull=False,
                    )
                    | Q(result_price_kind="unavailable")
                ),
                name="cover_decision_price_shape",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Decision receipts are immutable")
        return super().save(*args, **kwargs)


class ShadowCoverPrediction(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="shadow_predictions")
    model_release = models.ForeignKey(
        CoverModelRelease, on_delete=models.PROTECT, related_name="shadow_predictions"
    )
    target_time = models.DateTimeField()
    knowledge_cutoff = models.DateTimeField()
    result_price_cents = models.PositiveIntegerField(null=True, blank=True)
    result_low_cents = models.PositiveIntegerField(null=True, blank=True)
    result_high_cents = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("venue", "model_release", "target_time", "knowledge_cutoff"),
                name="unique_shadow_cover_prediction",
            )
        ]


class CoverTrainingRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_revision = models.CharField(max_length=160, unique=True)
    knowledge_cutoff = models.DateTimeField()
    service_nights = models.PositiveIntegerField()
    observations_seen = models.PositiveIntegerField()
    observations_admitted = models.PositiveIntegerField()
    provenance = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class CoverModelEvaluationReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    protocol_version = models.CharField(max_length=80)
    challenger = models.ForeignKey(
        CoverModelRelease,
        on_delete=models.PROTECT,
        related_name="challenger_evaluation_receipts",
    )
    incumbent = models.ForeignKey(
        CoverModelRelease,
        on_delete=models.PROTECT,
        related_name="incumbent_evaluation_receipts",
    )
    challenger_training_revision = models.ForeignKey(
        CoverTrainingRevision,
        on_delete=models.PROTECT,
        related_name="challenger_evaluation_receipts",
    )
    evaluation_data_revision = models.ForeignKey(
        CoverTrainingRevision,
        on_delete=models.PROTECT,
        related_name="evaluation_receipts",
    )
    evaluator_code_revision = models.CharField(max_length=80)
    evaluation_start = models.DateTimeField()
    evaluation_cutoff = models.DateTimeField()
    challenger_artifact_sha256 = models.CharField(max_length=64)
    incumbent_artifact_sha256 = models.CharField(max_length=64)
    row_selection_sha256 = models.CharField(max_length=64)
    metrics = models.JSONField(default=dict)
    gates = models.JSONField(default=dict)
    not_evaluable_dimensions = models.JSONField(default=dict)
    challenger_won = models.BooleanField(default=False)
    promotion_eligible = models.BooleanField(default=False)
    receipt_sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "protocol_version",
                    "challenger",
                    "incumbent",
                    "evaluation_data_revision",
                ),
                name="unique_cover_model_evaluation",
            ),
            models.CheckConstraint(
                condition=Q(evaluation_cutoff__gt=models.F("evaluation_start")),
                name="cover_model_evaluation_positive_window",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Model evaluation receipts are immutable")
        return super().save(*args, **kwargs)
