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

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        account = self.model(email=self.normalize_email(email), **extra_fields)
        if password:
            account.set_password(password)
        else:
            account.set_unusable_password()
        account.save(using=self._db)
        return account

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must be staff and a superuser")
        return self.create_user(email, password, **extra_fields)


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
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)


class InstallationCredential(models.Model):
    actor = models.OneToOneField(
        InstallationActor, on_delete=models.CASCADE, related_name="credential"
    )
    verifier = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.verifier, candidate)


class InstallationOperationReceipt(models.Model):
    class Operation(models.TextChoices):
        CREATE = "create", "Create"
        ROTATE = "rotate", "Rotate"

    request_id = models.UUIDField(primary_key=True, editable=False)
    operation = models.CharField(max_length=16, choices=Operation.choices)
    request_verifier = models.CharField(max_length=64)
    actor = models.OneToOneField(
        InstallationActor,
        on_delete=models.CASCADE,
        related_name="issuance_receipt",
    )
    completed_at = models.DateTimeField(auto_now_add=True)


class ActorAccountLink(models.Model):
    actor = models.OneToOneField(
        InstallationActor, on_delete=models.CASCADE, related_name="account_link"
    )
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="actor_links")
    # The link is durable privacy/deletion authority. Logout only disables its
    # use as an account trust and submission-attribution signal.
    is_attribution_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)


class ActorAccountLinkReceipt(models.Model):
    """Durable idempotency result for every accepted link request UUID."""

    request_id = models.UUIDField(primary_key=True, editable=False)
    link = models.ForeignKey(
        ActorAccountLink,
        on_delete=models.CASCADE,
        related_name="request_receipts",
    )
    completed_at = models.DateTimeField(auto_now_add=True)


class SessionTokenVerifier(models.Model):
    verifier = models.CharField(max_length=64, unique=True)
    session_key = models.CharField(max_length=64, db_index=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="session_token_verifiers",
        null=True,
        blank=True,
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.verifier, candidate)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class AllauthRateLimitCache(models.Model):
    """Schema owner for Django's DatabaseCache used by allauth rate limits."""

    cache_key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()
    expires = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "allauth_rate_limits"
        verbose_name = "allauth rate-limit cache entry"
        verbose_name_plural = "allauth rate-limit cache entries"


class IdentityRateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=180)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class AccountDeletionReceipt(models.Model):
    """Unlinkable proof that one high-entropy deletion request committed."""

    request_id = models.UUIDField(primary_key=True, editable=False)
    completed_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
