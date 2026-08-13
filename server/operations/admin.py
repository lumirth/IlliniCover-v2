from django.contrib import admin
from submissions.admin import ImmutableAdmin

from operations.models import AuditEvent, DatasetImportRun, DatasetRelease, JobRun

for model in (DatasetRelease, DatasetImportRun, JobRun, AuditEvent):
    admin.site.register(model, ImmutableAdmin)
