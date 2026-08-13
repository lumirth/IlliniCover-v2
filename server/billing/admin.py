from django.contrib import admin
from operations.admin_support import ImmutableAdminMixin

from billing.models import AccountEntitlement, ProviderDeletionRequest, RevenueCatEvent


@admin.register(AccountEntitlement)
class AccountEntitlementAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "account",
        "entitlement_identifier",
        "environment",
        "is_active",
        "expires_at",
        "updated_at",
    )
    list_filter = ("entitlement_identifier", "environment", "is_active")
    search_fields = ("account__email", "account__id")
    readonly_fields = tuple(field.name for field in AccountEntitlement._meta.fields)


@admin.register(RevenueCatEvent)
class RevenueCatEventAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "provider_event_id",
        "event_type",
        "environment",
        "app_user_id",
        "received_at",
        "processed_at",
    )
    list_filter = ("environment", "event_type")
    search_fields = ("provider_event_id", "app_user_id")
    readonly_fields = tuple(field.name for field in RevenueCatEvent._meta.fields)


@admin.register(ProviderDeletionRequest)
class ProviderDeletionRequestAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("provider_customer_id", "status", "attempts", "requested_at", "completed_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in ProviderDeletionRequest._meta.fields)
