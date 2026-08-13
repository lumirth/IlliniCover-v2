import uuid

from django.db import models


class HandbookPage(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=160)
    summary = models.TextField(blank=True)
    body_markdown = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    sort_order = models.PositiveSmallIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "title")
