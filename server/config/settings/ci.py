"""Fail-closed CI settings backed by the workflow's ephemeral PostgreSQL."""

import os

from django.core.exceptions import ImproperlyConfigured

from config.database import database_from_url

from .test import *  # noqa: F403

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise ImproperlyConfigured("CI requires DATABASE_URL for ephemeral PostgreSQL")

DATABASES = {"default": database_from_url(database_url)}
