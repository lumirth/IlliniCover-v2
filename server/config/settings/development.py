import os

from config.database import database_from_url

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SESSION_COOKIE_SECURE = False

if database_url := os.environ.get("DATABASE_URL"):
    DATABASES = {"default": database_from_url(database_url)}
