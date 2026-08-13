from django.contrib import admin

from submissions.models import Submission, SubmissionPrivateContext


class ImmutableAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Submission)
class SubmissionAdmin(ImmutableAdmin):
    list_display = (
        "id",
        "kind",
        "venue",
        "observed_at_client",
        "received_at_server",
        "time_quality",
    )
    list_filter = ("kind", "time_quality", "venue")
    search_fields = ("id", "source_record_key")
    readonly_fields = tuple(field.name for field in Submission._meta.fields)


@admin.register(SubmissionPrivateContext)
class SubmissionPrivateContextAdmin(ImmutableAdmin):
    list_display = ("submission", "erased_at", "location_permission")
    readonly_fields = tuple(field.name for field in SubmissionPrivateContext._meta.fields)

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm(
            "submissions.view_submissionprivatecontext"
        )

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)
