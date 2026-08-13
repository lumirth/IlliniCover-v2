import uuid

from django.core.exceptions import ValidationError
from django.db import models
from submissions.models import Submission
from venues.models import Venue


class DealFamily(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_name = models.CharField(max_length=160)
    source_identifier = models.CharField(max_length=80, unique=True, null=True, blank=True)
    category = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("category", "canonical_name"), name="unique_deal_family_name_per_category"
            )
        ]


class DealAlias(models.Model):
    family = models.ForeignKey(DealFamily, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DealDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="deal_definitions")
    family = models.ForeignKey(
        DealFamily, on_delete=models.PROTECT, related_name="definitions", null=True, blank=True
    )
    display_name = models.CharField(max_length=180)
    category = models.CharField(max_length=40)
    price_kind = models.CharField(max_length=24)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    price_low_cents = models.PositiveIntegerField(null=True, blank=True)
    price_high_cents = models.PositiveIntegerField(null=True, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=80, blank=True)
    serving_format = models.CharField(max_length=120, blank=True)
    timing_description = models.CharField(max_length=160, blank=True)
    timing_known = models.BooleanField(default=False)
    while_supplies_last = models.BooleanField(default=False)
    status = models.CharField(max_length=24, default="likely")
    prediction_id = models.UUIDField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DealEvidenceEvent(models.Model):
    class Action(models.TextChoices):
        ADD_MISSING = "ADD_MISSING", "Add missing"
        CONFIRM_PRESENT = "CONFIRM_PRESENT", "Confirm present"
        DENY_PRESENT = "DENY_PRESENT", "Deny present"
        CORRECT = "CORRECT", "Correct"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(
        Submission, on_delete=models.PROTECT, related_name="deal_evidence_event"
    )
    action = models.CharField(max_length=24, choices=Action.choices)
    target_deal = models.ForeignKey(
        DealDefinition,
        on_delete=models.PROTECT,
        related_name="evidence_events",
        null=True,
        blank=True,
    )
    target_prediction_id = models.UUIDField(null=True, blank=True)
    target_evidence = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="targeted_by",
        null=True,
        blank=True,
    )
    submitted_deal_shape = models.JSONField(null=True, blank=True)
    service_date_local = models.DateField()
    target_local_datetime = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="corrections", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)


class HistoricalDealFact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_record_key = models.CharField(max_length=500, unique=True)
    source_dataset = models.CharField(max_length=120)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="historical_deal_facts")
    family = models.ForeignKey(
        DealFamily, on_delete=models.PROTECT, related_name="historical_facts", null=True, blank=True
    )
    # Normalized server-only search text derived from historical source names.
    # It intentionally cannot reconstruct or expose the raw extracted offer text.
    private_search_text = models.CharField(max_length=180, blank=True)
    display_name = models.CharField(max_length=180)
    category = models.CharField(max_length=40)
    price_kind = models.CharField(max_length=24)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    relative_percent = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=120, blank=True)
    service_date_local = models.DateField()
    timing_kind = models.CharField(max_length=40)
    timing_start_local = models.TimeField(null=True, blank=True)
    timing_end_local = models.TimeField(null=True, blank=True)
    timing_time_local = models.TimeField(null=True, blank=True)
    while_supplies_last = models.BooleanField(default=False)
    source_post_key = models.CharField(max_length=300)
    source_payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Imported historical deal facts are immutable")
        return super().save(*args, **kwargs)


class DealPredictionRelease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    predictor_version = models.CharField(max_length=80)
    code_revision = models.CharField(max_length=80)
    training_data_revision = models.CharField(max_length=160)
    parameters = models.JSONField(default=dict)
    evaluation_metrics = models.JSONField(default=dict)
    is_authoritative = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("predictor_version", "training_data_revision"),
                name="unique_deal_prediction_release",
            ),
            models.UniqueConstraint(
                fields=("is_authoritative",),
                condition=models.Q(is_authoritative=True),
                name="one_authoritative_deal_predictor",
            ),
        ]

    IMMUTABLE_FIELDS = (
        "predictor_version",
        "code_revision",
        "training_data_revision",
        "parameters",
        "evaluation_metrics",
        "created_at",
    )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Deal release artifacts and receipts are immutable")
        return super().save(*args, **kwargs)


class DealPrediction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    release = models.ForeignKey(
        DealPredictionRelease, on_delete=models.PROTECT, related_name="predictions"
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="deal_predictions")
    deal_definition = models.ForeignKey(
        DealDefinition, on_delete=models.PROTECT, related_name="predictions"
    )
    service_date_local = models.DateField()
    support_nights = models.PositiveIntegerField()
    comparable_nights = models.PositiveIntegerField()
    latest_evidence_date = models.DateField()
    rank = models.PositiveIntegerField()
    status = models.CharField(max_length=24, default="likely")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("release", "venue", "deal_definition", "service_date_local"),
                name="unique_deal_prediction",
            ),
            models.UniqueConstraint(
                fields=("release", "venue", "service_date_local", "rank"),
                name="unique_deal_prediction_rank",
            ),
            models.CheckConstraint(
                condition=models.Q(rank__gte=1), name="deal_prediction_rank_gte_1"
            ),
        ]

    IMMUTABLE_FIELDS = (
        "release_id",
        "venue_id",
        "deal_definition_id",
        "service_date_local",
        "support_nights",
        "comparable_nights",
        "latest_evidence_date",
        "rank",
        "status",
        "created_at",
    )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Materialized deal predictions are immutable")
        return super().save(*args, **kwargs)
