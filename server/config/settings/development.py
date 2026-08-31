import os

from django.core.exceptions import ImproperlyConfigured

from config.database import database_from_url

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SESSION_COOKIE_SECURE = False

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise ImproperlyConfigured("Development requires DATABASE_URL; use the repository scripts")
DATABASES = {"default": database_from_url(database_url)}
