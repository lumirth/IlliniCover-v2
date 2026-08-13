from django.contrib import admin
from submissions.admin import ImmutableAdmin

from deals.models import (
    DealAlias,
    DealDefinition,
    DealEvidenceEvent,
    DealFamily,
    DealPrediction,
    DealPredictionRelease,
    HistoricalDealFact,
)

for model in (
    DealFamily,
    DealAlias,
    DealDefinition,
    DealEvidenceEvent,
    HistoricalDealFact,
    DealPredictionRelease,
    DealPrediction,
):
    admin.site.register(model, ImmutableAdmin)
