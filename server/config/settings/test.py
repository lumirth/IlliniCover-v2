from .base import *  # noqa: F403

SECRET_KEY = "test-secret-key"
SESSION_TOKEN_PEPPER = "test-session-token-pepper"
INSTALLATION_TOKEN_PEPPER = "test-installation-token-pepper"
ALLOWED_HOSTS = ["testserver"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
