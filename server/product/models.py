from __future__ import annotations

import hmac
import uuid
from typing import ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class AccountManager(BaseUserManager["Account"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **fields):
        if not email:
            raise ValueError("An email address is required")
        account = self.model(email=self.normalize_email(email), **fields)
        account.set_password(password) if password else account.set_unusable_password()
        account.save(using=self._db)
        return account

    def create_superuser(self, email: str, password: str, **fields):
        fields.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **fields)


class Account(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    USERNAME_FIELD: ClassVar[str] = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []
    objects = AccountManager()

    def __str__(self) -> str:
        return self.email


class InstallationActor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verifier = models.CharField(max_length=64, unique=True)
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="installations", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.verifier, candidate)


class SessionTokenVerifier(models.Model):
    verifier = models.CharField(max_length=64, unique=True)
    session_key = models.CharField(max_length=64, db_index=True)
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="session_token_verifiers", null=True
    )
    def matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.verifier, candidate)


class AllauthRateLimitCache(models.Model):
    cache_key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()
    expires = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "allauth_rate_limits"


class RateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=180)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class Venue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=240, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    opened_year = models.PositiveSmallIntegerField(null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Submission(models.Model):
    class Kind(models.TextChoices):
        OBSERVATIONS = "observations", "Cover and vibes"
        DEAL_EVIDENCE = "deal_evidence", "Deal evidence"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="submissions")
    observed_at_client = models.DateTimeField()
    received_at_server = models.DateTimeField(default=timezone.now)
    time_quality = models.CharField(max_length=24, default="plausible")
    vantage_point = models.CharField(max_length=16, default="unknown")
    client_platform = models.CharField(max_length=24, blank=True)
    entry_point = models.CharField(max_length=40, blank=True)
    source_record_key = models.CharField(max_length=500, blank=True, unique=True, null=True)
    independence_group = models.UUIDField(null=True)
    cover_price_cents = models.PositiveIntegerField(null=True)
    cover_interaction = models.CharField(max_length=24, blank=True)
    cover_echo = models.JSONField(default=dict)
    vibes = models.JSONField(default=list)
    trust = models.JSONField(default=dict)

    class Meta:
        ordering = ("-observed_at_client", "-received_at_server")


class SubmissionPrivateContext(models.Model):
    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="private_context"
    )
    actor = models.ForeignKey(
        InstallationActor, on_delete=models.SET_NULL, null=True, related_name="submission_contexts"
    )
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, related_name="submission_contexts"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    location_accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    location_permission = models.CharField(max_length=24, blank=True)


class AdvertisedAdmission(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="advertised_admissions")
    price_cents = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True)
    qualification = models.CharField(max_length=240, blank=True)
    published_at = models.DateTimeField(default=timezone.now)
    provenance = models.CharField(max_length=500)


class DealFamily(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_name = models.CharField(max_length=160)
    category = models.CharField(max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("category", "canonical_name"), name="unique_deal_family"
            )
        ]


class HistoricalDealFact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_record_key = models.CharField(max_length=500, unique=True)
    source = models.CharField(max_length=500)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="historical_deals")
    family = models.ForeignKey(
        DealFamily, on_delete=models.PROTECT, related_name="facts"
    )
    display_name = models.CharField(max_length=180)
    price_kind = models.CharField(max_length=24)
    price_cents = models.PositiveIntegerField(null=True)
    discount_percent = models.DecimalField(max_digits=8, decimal_places=3, null=True)
    unit = models.CharField(max_length=120, blank=True)
    service_date_local = models.DateField()
    timing_description = models.CharField(max_length=160, blank=True)
    while_supplies_last = models.BooleanField(default=False)


class DealEvidenceEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="deal_event"
    )
    action = models.CharField(max_length=24)
    target_id = models.UUIDField(null=True)
    submitted_shape = models.JSONField(null=True)
    service_date_local = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)


class HandbookPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=160)
    summary = models.TextField(blank=True)
    body_markdown = models.TextField()
    published = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    published_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "title")


class AccountEntitlement(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="entitlement")
    is_active = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)


class RevenueCatEvent(models.Model):
    provider_event_id = models.CharField(max_length=160, primary_key=True)


class ProviderDeletionRequest(models.Model):
    provider_customer_id = models.CharField(max_length=160, primary_key=True)
    queued = models.BooleanField(default=False)
