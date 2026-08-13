import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountEntitlement(models.Model):
    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"
        PROVIDER_AGGREGATE = "provider_aggregate", "Provider aggregate"

    account = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entitlements"
    )
    entitlement_identifier = models.CharField(max_length=80, default="premium")
    environment = models.CharField(
        max_length=24,
        choices=Environment.choices,
        default=Environment.PROVIDER_AGGREGATE,
    )
    is_active = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    provider_updated_at = models.DateTimeField(null=True, blank=True)
    # One local clock for ordering provider snapshots against webhook receipt.
    # provider_updated_at remains provider provenance and is never compared to
    # this local authority clock.
    authority_observed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("account", "entitlement_identifier", "environment"),
                name="unique_account_entitlement_environment",
            )
        ]


class RevenueCatEvent(models.Model):
    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"
        UNKNOWN = "unknown", "Unknown or not supplied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_event_id = models.CharField(max_length=160, unique=True)
    event_type = models.CharField(max_length=80)
    environment = models.CharField(
        max_length=16, choices=Environment.choices, default=Environment.UNKNOWN
    )
    app_user_id = models.CharField(max_length=160, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)


class ProviderDeletionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued at provider"
        SUCCEEDED = "succeeded", "Succeeded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=40, default="revenuecat")
    provider_customer_id = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    requested_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
