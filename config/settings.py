"""
Django settings for School Pickup Coordinator.

All environment-specific values come from environment variables via
django-environ. See `.env.example` for the full list.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CLERK_AUTHORIZED_PARTIES=(list, []),
)

# Read .env if present (local dev); real deployments set env vars directly.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-only-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "django_celery_beat",
    "drf_spectacular",
    "channels",
    # Local apps
    "core",
    "accounts",
    "families",
    "schools",
    "carpool",
    "trips",
    "chat",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database — PostgreSQL via psycopg 3
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://pickme:pickme@localhost:5432/pickme",
    ),
}

AUTH_USER_MODEL = "accounts.User"

# Redis — shared by the Celery broker and (from Stage 4) the channel layer
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    },
}

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "expire-stale-swap-requests": {
        "task": "carpool.tasks.expire_stale_swap_requests",
        "schedule": 60 * 60,  # hourly, per SYSTEMS-DEEP-DIVE.md
    },
    "cleanup-old-location-pings": {
        "task": "trips.tasks.cleanup_old_location_pings",
        "schedule": crontab(hour=3, minute=0),  # nightly, per SYSTEMS-DEEP-DIVE.md
    },
}

# Pending swap requests older than this are auto-expired
SWAP_REQUEST_EXPIRY_HOURS = env.int("SWAP_REQUEST_EXPIRY_HOURS", default=48)

# Maps / trip tracking
MAPS_BACKEND = env("MAPS_BACKEND", default="fake")  # "fake" | "google"
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")
LOCATION_PING_RETENTION_DAYS = env.int("LOCATION_PING_RETENTION_DAYS", default=30)
ETA_THROTTLE_SECONDS = env.int("ETA_THROTTLE_SECONDS", default=30)

# Clerk auth
CLERK_ISSUER = env("CLERK_ISSUER", default="")
CLERK_JWKS_URL = env(
    "CLERK_JWKS_URL",
    default=f"{CLERK_ISSUER}/.well-known/jwks.json" if CLERK_ISSUER else "",
)
# Origins allowed in the token's `azp` claim (empty list = skip the check)
CLERK_AUTHORIZED_PARTIES = env("CLERK_AUTHORIZED_PARTIES")
CLERK_WEBHOOK_SIGNING_SECRET = env("CLERK_WEBHOOK_SIGNING_SECRET", default="")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.ClerkJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "core.exceptions.envelope_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "School Pickup Coordinator API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Family invites etc.; console backend until a real provider is wired up
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@pickme.local")

AUTH_PASSWORD_VALIDATORS = []  # Clerk owns credentials; Django never sees passwords

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
