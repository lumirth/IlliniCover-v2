from django.db import models
from django.db.models import Q
from submissions.models import Submission


class VibeObservation(models.Model):
    class Dimension(models.TextChoices):
        LINE_LENGTH = "line_length", "Line length"
        LINE_SPEED = "line_speed", "Line speed"
        CROWD_LEVEL = "crowd_level", "Crowd level"

    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="vibe_observations"
    )
    dimension = models.CharField(max_length=24, choices=Dimension.choices)
    value = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "dimension"), name="one_vibe_dimension_per_submission"
            ),
            models.CheckConstraint(
                condition=(
                    Q(dimension="line_length", value__in=("short", "medium", "long"))
                    | Q(dimension="line_speed", value__in=("slow", "normal", "fast"))
                    | Q(dimension="crowd_level", value__in=("quiet", "busy", "packed"))
                ),
                name="vibe_value_matches_dimension",
            ),
        ]
