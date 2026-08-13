import uuid

from django.db import models
from venues.models import Venue


class SourceFetch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_identifier = models.CharField(max_length=120)
    fetched_at = models.DateTimeField()
    source_url = models.URLField(max_length=500, blank=True)
    external_key = models.CharField(max_length=200, blank=True)
    payload_hash = models.CharField(max_length=64)
    parser_version = models.CharField(max_length=80)
    status = models.CharField(max_length=24)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source_identifier", "external_key", "payload_hash"),
                name="unique_source_payload",
            )
        ]


class SourceHealth(models.Model):
    source_identifier = models.CharField(max_length=120, unique=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class AcademicPeriod(models.Model):
    kind = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    source_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.PROTECT, related_name="academic_periods"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "name", "starts_at", "ends_at"), name="unique_academic_period"
            )
        ]


class SportsEvent(models.Model):
    sport = models.CharField(max_length=80)
    opponent = models.CharField(max_length=160, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_home = models.BooleanField(default=False)
    external_key = models.CharField(max_length=200, unique=True)
    source_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.PROTECT, related_name="sports_events"
    )


class WeatherRecord(models.Model):
    observed_at = models.DateTimeField()
    valid_at = models.DateTimeField()
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    precipitation_mm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    wind_speed_mps = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.PROTECT, related_name="weather_records"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("valid_at", "source_fetch"), name="unique_weather_record_per_fetch"
            )
        ]


class TraditionEvent(models.Model):
    name = models.CharField(max_length=160)
    service_date_local = models.DateField()
    provenance = models.CharField(max_length=240)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "service_date_local"), name="unique_tradition_event"
            )
        ]


class VenueEvent(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="context_events")
    name = models.CharField(max_length=180)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    source_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.PROTECT, related_name="venue_events"
    )


class AdvertisedAdmission(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="advertised_admissions")
    price_cents = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    qualification = models.CharField(max_length=240, blank=True)
    is_unconditional = models.BooleanField(default=False)
    source_fetch = models.ForeignKey(
        SourceFetch, on_delete=models.PROTECT, related_name="advertised_admissions"
    )
