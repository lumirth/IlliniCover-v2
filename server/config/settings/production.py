import os

from django.core.exceptions import ImproperlyConfigured

from config.database import database_from_url
from config.secrets import secret_value

from .base import *  # noqa: F403

if CODE_REVISION in {"", "development"}:  # noqa: F405
    raise ImproperlyConfigured("CODE_REVISION must identify an immutable production revision")

DEPLOYMENT_ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "")
if DEPLOYMENT_ENVIRONMENT not in {"production", "preview"}:
    raise ImproperlyConfigured("DEPLOYMENT_ENVIRONMENT must be production or preview")
SENTRY_ENVIRONMENT = DEPLOYMENT_ENVIRONMENT

DATABASE_MODE = os.environ.get("DATABASE_MODE", "pooled")
if DATABASE_MODE not in {"pooled", "direct"}:
    raise ImproperlyConfigured("DATABASE_MODE must be pooled or direct")
database_secret_name = "DATABASE_URL_DIRECT" if DATABASE_MODE == "direct" else "DATABASE_URL"
DATABASE_URL = secret_value(database_secret_name, required=True)
DATABASES = {"default": database_from_url(DATABASE_URL)}
DATABASE_CONNECTION_MODE = DATABASE_MODE
SECRET_KEY = secret_value("DJANGO_SECRET_KEY", required=True)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "ALLOWED_HOSTS", ".run.app,api.illinicover.com,localhost,127.0.0.1"
    ).split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CSRF_TRUSTED_ORIGINS", "https://*.run.app,https://api.illinicover.com"
    ).split(",")
    if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = secret_value("EMAIL_HOST")
EMAIL_PORT = int(secret_value("EMAIL_PORT", default="587"))
EMAIL_HOST_USER = secret_value("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = secret_value("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = secret_value("EMAIL_USE_TLS", default="true").lower() in {"1", "true", "yes"}
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = secret_value(
    "DEFAULT_FROM_EMAIL", default="IlliniCover <noreply@illinicover.com>"
)

SENTRY_DSN = secret_value("SENTRY_DSN")
if SENTRY_DSN:
    from config.monitoring import configure_sentry

    configure_sentry(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=CODE_REVISION,  # noqa: F405
    )
