from operations.models import AuditEvent


class AuditedAdminMixin:
    """Record bounded Admin mutations without copying model contents into the audit log."""

    def _audit(self, request, obj, action: str) -> None:
        AuditEvent.objects.create(
            kind=f"admin.{action}",
            actor_kind="account",
            actor_reference=str(request.user.pk),
            target_reference=f"{obj._meta.label_lower}:{obj.pk}",
            metadata={"model": obj._meta.label_lower},
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)  # type: ignore[misc]
        self._audit(request, obj, "change" if change else "add")

    def delete_model(self, request, obj):
        self._audit(request, obj, "delete")
        super().delete_model(request, obj)  # type: ignore[misc]


class ImmutableAdminMixin:
    """Expose operational receipts and identity links without mutation paths."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)  # type: ignore[misc]
        actions.pop("delete_selected", None)
        return actions
