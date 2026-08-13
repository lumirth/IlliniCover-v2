import uuid

from django.db import models


class DatasetRelease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    content_hash = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=40)
    importer_version = models.CharField(max_length=80)
    source_manifest = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "content_hash"), name="unique_dataset_content_release"
            )
        ]


class DatasetImportRun(models.Model):
    release = models.ForeignKey(
        DatasetRelease, on_delete=models.PROTECT, related_name="import_runs"
    )
    code_revision = models.CharField(max_length=80)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rows_seen = models.PositiveIntegerField(default=0)
    rows_accepted = models.PositiveIntegerField(default=0)
    rows_rejected = models.PositiveIntegerField(default=0)
    result = models.CharField(max_length=24, default="running")


class JobRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    code_revision = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default="running")
    error = models.TextField(blank=True)
    result_summary = models.JSONField(default=dict)


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=120)
    actor_kind = models.CharField(max_length=40)
    actor_reference = models.CharField(max_length=160, blank=True)
    target_reference = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
