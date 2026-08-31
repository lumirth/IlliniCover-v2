import os
from pathlib import Path

from config.secrets import secret_value

SERVER_DIR = Path(__file__).resolve().parents[2]
REPOSITORY_DIR = SERVER_DIR.parent

SECRET_KEY = secret_value("DJANGO_SECRET_KEY", default="development-only-not-for-production")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "allauth.mfa",
    "ninja",
    "product",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.RequestIdMiddleware",
    "config.middleware.SensitiveResponseCacheMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "identity.middleware.AdminMfaEnrollmentMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES: dict[str, object] = {}

AUTH_USER_MODEL = "product.Account"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SITE_ID = 1

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = REPOSITORY_DIR / ".local" / "static"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True
REVENUECAT_WEBHOOK_AUTHORIZATION = secret_value(
    "REVENUECAT_WEBHOOK_AUTHORIZATION", bundle_name="REVENUECAT_WEBHOOK_AUTH_SECRET"
)
REVENUECAT_WEBHOOK_SIGNING_SECRET = secret_value(
    "REVENUECAT_WEBHOOK_SIGNING_SECRET", bundle_name="REVENUECAT_WEBHOOK_SIGNATURE_SECRET"
)
REVENUECAT_SECRET_API_KEY = secret_value(
    "REVENUECAT_SECRET_API_KEY", bundle_name="REVENUECAT_SECRET_API_KEY"
)
REVENUECAT_PROJECT_ID = secret_value("REVENUECAT_PROJECT_ID", default="proj72780529")
REVENUECAT_PREMIUM_ENTITLEMENT_RESOURCE_ID = secret_value(
    "REVENUECAT_PREMIUM_ENTITLEMENT_RESOURCE_ID", default="entlb2319dd271"
)
REVENUECAT_WEBHOOK_TOLERANCE_SECONDS = 300
CODE_REVISION = os.environ.get("CODE_REVISION", "development")
DEPLOYMENT_ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "local")
PUBLIC_API_ORIGIN = os.environ.get("PUBLIC_API_ORIGIN", "http://localhost:8000")
TRUSTED_XFF_PROXY_HOPS = int(os.environ.get("TRUSTED_XFF_PROXY_HOPS", "1"))

HEADLESS_ONLY = False
HEADLESS_CLIENTS = ("app",)
HEADLESS_TOKEN_STRATEGY = "identity.tokens.VerifierOnlySessionTokenStrategy"
MFA_SUPPORTED_TYPES = ["recovery_codes", "totp"]
MFA_TOTP_ISSUER = "IlliniCover"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = True
ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_RESEND = 2
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_SUPPORTS_RESEND = 2
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 300
PENDING_EMAIL_AUTH_SESSION_TTL_SECONDS = 300
ACCOUNT_RATE_LIMITS = {"confirm_email": "3/m/key,20/m/ip"}
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_ADAPTER = "identity.adapters.IlliniCoverAccountAdapter"
LOGIN_URL = "/admin-auth/login/"
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[IlliniCover] "
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "IlliniCover <noreply@localhost>")

COVER_LIVE_HORIZON_SECONDS = int(os.environ.get("COVER_LIVE_HORIZON_SECONDS", "3600"))
VIBE_FRESHNESS_SECONDS = {
    "line_length": int(os.environ.get("VIBE_LINE_LENGTH_HORIZON_SECONDS", "1800")),
    "line_speed": int(os.environ.get("VIBE_LINE_SPEED_HORIZON_SECONDS", "1800")),
    "crowd_level": int(os.environ.get("VIBE_CROWD_LEVEL_HORIZON_SECONDS", "3600")),
}
CLIENT_CLOCK_FUTURE_TOLERANCE_SECONDS = int(
    os.environ.get("CLIENT_CLOCK_FUTURE_TOLERANCE_SECONDS", "300")
)
CLIENT_INTERACTION_MAX_AGE_SECONDS = int(
    os.environ.get("CLIENT_INTERACTION_MAX_AGE_SECONDS", "86400")
)
IMPOSSIBLE_MOVEMENT_SPEED_MPS = float(os.environ.get("IMPOSSIBLE_MOVEMENT_SPEED_MPS", "250"))
RAPID_REPORT_WINDOW_SECONDS = int(os.environ.get("RAPID_REPORT_WINDOW_SECONDS", "15"))
SUBMISSION_RATE_LIMITS = {
    "actor": (int(os.environ.get("REPORT_ACTOR_LIMIT", "20")), 600),
    "account": (int(os.environ.get("REPORT_ACCOUNT_LIMIT", "30")), 600),
    "venue": (int(os.environ.get("REPORT_VENUE_LIMIT", "120")), 600),
    "network": (int(os.environ.get("REPORT_NETWORK_LIMIT", "60")), 600),
}
TIME_MACHINE_CURRENT_TOLERANCE_SECONDS = int(
    os.environ.get("TIME_MACHINE_CURRENT_TOLERANCE_SECONDS", "60")
)
TIME_MACHINE_MAX_PAST_DAYS = int(os.environ.get("TIME_MACHINE_MAX_PAST_DAYS", "3650"))
TIME_MACHINE_MAX_FUTURE_DAYS = int(os.environ.get("TIME_MACHINE_MAX_FUTURE_DAYS", "365"))
TIME_MACHINE_ACCOUNT_RATE_LIMIT = (
    int(os.environ.get("TIME_MACHINE_ACCOUNT_LIMIT", "60")),
    int(os.environ.get("TIME_MACHINE_RATE_WINDOW_SECONDS", "3600")),
)
TIME_MACHINE_NETWORK_RATE_LIMIT = (
    int(os.environ.get("TIME_MACHINE_NETWORK_LIMIT", "120")),
    int(os.environ.get("TIME_MACHINE_RATE_WINDOW_SECONDS", "3600")),
)
INSTALLATION_ISSUANCE_RATE_LIMIT = (
    int(os.environ.get("INSTALLATION_ISSUANCE_NETWORK_LIMIT", "8")),
    int(os.environ.get("INSTALLATION_ISSUANCE_WINDOW_SECONDS", "3600")),
)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "allauth_rate_limits",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 10_000},
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "config.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
