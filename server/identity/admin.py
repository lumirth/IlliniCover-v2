from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from operations.admin_support import AuditedAdminMixin, ImmutableAdminMixin

from identity.models import (
    Account,
    AccountDeletionReceipt,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    IdentityRateBucket,
    InstallationActor,
    InstallationOperationReceipt,
)


@admin.register(Account)
class AccountAdmin(AuditedAdminMixin, UserAdmin):
    model = Account
    ordering = ("email",)
    list_display = ("email", "is_staff", "is_active", "created_at")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("display_name",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def has_delete_permission(self, request, obj=None):
        # The API deletion service is the sole erasure path because it also
        # scrubs sessions, private evidence, and provider customer metadata.
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(InstallationActor)
class InstallationActorAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("id", "created_at", "last_seen_at")
    readonly_fields = tuple(field.name for field in InstallationActor._meta.fields)


@admin.register(ActorAccountLink)
class ActorAccountLinkAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("actor", "account", "is_attribution_active", "linked_at")
    search_fields = ("actor__id", "account__id", "account__email")
    readonly_fields = tuple(field.name for field in ActorAccountLink._meta.fields)


@admin.register(ActorAccountLinkReceipt)
class ActorAccountLinkReceiptAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("request_id", "link", "completed_at")
    readonly_fields = tuple(field.name for field in ActorAccountLinkReceipt._meta.fields)


@admin.register(InstallationOperationReceipt)
class InstallationOperationReceiptAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("request_id", "operation", "actor", "completed_at")
    readonly_fields = tuple(field.name for field in InstallationOperationReceipt._meta.fields)


@admin.register(AccountDeletionReceipt)
class AccountDeletionReceiptAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("request_id", "completed_at", "expires_at")
    readonly_fields = tuple(field.name for field in AccountDeletionReceipt._meta.fields)


@admin.register(IdentityRateBucket)
class IdentityRateBucketAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("key", "count", "expires_at")
    readonly_fields = tuple(field.name for field in IdentityRateBucket._meta.fields)
