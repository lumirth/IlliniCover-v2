from django.contrib import admin
from submissions.admin import ImmutableAdmin

from context.models import (
    AcademicPeriod,
    AdvertisedAdmission,
    SourceFetch,
    SourceHealth,
    SportsEvent,
    TraditionEvent,
    VenueEvent,
    WeatherRecord,
)

for model in (
    SourceFetch,
    SourceHealth,
    AcademicPeriod,
    SportsEvent,
    WeatherRecord,
    TraditionEvent,
    VenueEvent,
    AdvertisedAdmission,
):
    admin.site.register(model, ImmutableAdmin)
