import uuid

from django.db import models


class Venue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=240, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    opened_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name


class VenueAlias(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=120, unique=True)
    source = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return self.alias
