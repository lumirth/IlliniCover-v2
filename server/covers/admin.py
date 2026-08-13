from django.contrib import admin
from submissions.admin import ImmutableAdmin

from covers.models import (
    CoverDecision,
    CoverModelEvaluationReceipt,
    CoverModelRelease,
    CoverObservation,
    CoverTrainingRevision,
    ShadowCoverPrediction,
)

for model in (
    CoverObservation,
    CoverDecision,
    CoverModelEvaluationReceipt,
    CoverModelRelease,
    ShadowCoverPrediction,
    CoverTrainingRevision,
):
    admin.site.register(model, ImmutableAdmin)
