from django.contrib import admin
from operations.admin_support import AuditedAdminMixin

from handbook.models import HandbookPage


@admin.register(HandbookPage)
class HandbookPageAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "status", "sort_order", "published_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "summary", "body_markdown")
    prepopulated_fields = {"slug": ("title",)}
