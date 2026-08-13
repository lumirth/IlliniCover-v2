from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from identity.models import InstallationActor
from venues.models import Venue


class Submission(models.Model):
    class Kind(models.TextChoices):
        OBSERVATIONS = "observations", "Cover and vibes"
        DEAL_EVIDENCE = "deal_evidence", "Deal evidence"

    class TimeQuality(models.TextChoices):
        UNASSESSED = "unassessed", "Unassessed"
        PLAUSIBLE = "plausible", "Plausible"
        FUTURE_SKEW = "future_skew", "Future skew"
        STALE_INTERACTION = "stale_interaction", "Stale interaction"

    class VantagePoint(models.TextChoices):
        OUTSIDE = "outside", "Outside"
        INSIDE = "inside", "Inside"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, editable=False)
    request_fingerprint = models.CharField(max_length=64)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="submissions")
    observed_at_client = models.DateTimeField()
    received_at_server = models.DateTimeField(default=timezone.now)
    time_quality = models.CharField(
        max_length=24, choices=TimeQuality.choices, default=TimeQuality.UNASSESSED
    )
    vantage_point = models.CharField(
        max_length=16, choices=VantagePoint.choices, default=VantagePoint.UNKNOWN
    )
    client_platform = models.CharField(max_length=24, blank=True)
    client_version = models.CharField(max_length=40, blank=True)
    entry_point = models.CharField(max_length=40, blank=True)
    source_kind = models.CharField(max_length=40, blank=True)
    source_record_key = models.CharField(max_length=500, blank=True, unique=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-observed_at_client", "-received_at_server")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Accepted submissions are immutable")
        return super().save(*args, **kwargs)


class SubmissionPrivateContext(models.Model):
    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="private_context"
    )
    actor = models.ForeignKey(
        InstallationActor,
        on_delete=models.SET_NULL,
        related_name="submission_contexts",
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="submission_contexts",
        null=True,
        blank=True,
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    location_permission = models.CharField(max_length=24, blank=True)
    network_verifier = models.CharField(max_length=64, blank=True)
    evidence_snapshot = models.JSONField(default=dict)
    erased_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(latitude__isnull=True) & Q(longitude__isnull=True))
                    | (Q(latitude__isnull=False) & Q(longitude__isnull=False))
                ),
                name="private_location_complete_pair",
            )
        ]


class SubmissionRateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=180)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
