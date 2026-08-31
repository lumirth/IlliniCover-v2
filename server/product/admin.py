from django.contrib import admin

from product import models

for model in (
    models.Account,
    models.Venue,
    models.Submission,
    models.AdvertisedAdmission,
    models.DealEvidenceEvent,
    models.HandbookPage,
    models.AccountEntitlement,
    models.RevenueCatEvent,
):
    admin.site.register(model)
