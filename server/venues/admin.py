from django.contrib import admin
from operations.admin_support import AuditedAdminMixin

from venues.models import Venue, VenueAlias


@admin.register(Venue)
class VenueAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "address", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "address")


@admin.register(VenueAlias)
class VenueAliasAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("alias", "venue", "source")
    search_fields = ("alias", "venue__name")
