"""
Django settings for the fdsrun portal.

Everything that differs between a developer laptop, staging and production
comes from environment variables (see deploy/cloud-init.yml and docs/sekrety.md).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

env = os.environ.get

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ENVIRONMENT = env("FDSRUN_ENV", "dev")  # dev | staging | production

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.accounts",
    "apps.jobs",
    "apps.compute",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "fdsrun.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "fdsrun.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "fdsrun.wsgi.application"

if env("DATABASE_URL"):
    # postgres://user:password@host:port/name
    from urllib.parse import urlparse

    u = urlparse(env("DATABASE_URL"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": u.path.lstrip("/"),
            "USER": u.username,
            "PASSWORD": u.password,
            "HOST": u.hostname,
            "PORT": u.port or 5432,
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "dev.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "jobs:list"
LOGOUT_REDIRECT_URL = "home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "pl"
LANGUAGES = [("pl", "Polski"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if ENVIRONMENT != "dev" else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Job files (input .fds, results) live here; an S3-compatible store can replace it later.
JOB_DATA_ROOT = Path(env("JOB_DATA_ROOT", str(BASE_DIR / "data" / "jobs")))
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "50"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery
CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env("CELERY_EAGER", "0") == "1"
CELERY_TIMEZONE = TIME_ZONE

# Security (behind Caddy, which terminates TLS)
if ENVIRONMENT != "dev":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# Compute (Hetzner Cloud)
HCLOUD_TOKEN = env("HCLOUD_TOKEN", "")
HCLOUD_LOCATION = env("HCLOUD_LOCATION", "nbg1")
COMPUTE_IMAGE = env("COMPUTE_IMAGE", "ghcr.io/baranero/fdsrun-v2/fds:6.10.1")
PORTAL_URL = env("PORTAL_URL", "http://localhost:8000")  # how compute machines reach us
COMPUTE_HEARTBEAT_TIMEOUT_S = int(env("COMPUTE_HEARTBEAT_TIMEOUT_S", "600"))
COMPUTE_LABEL = env("COMPUTE_LABEL", f"fdsrun-{ENVIRONMENT}")

# Pricing (decisions 5-8 in the implementation plan)
PRICING = {
    "eur_pln": float(env("EUR_PLN", "4.25")),
    "multiplier_company": float(env("PRICE_MULTIPLIER_COMPANY", "6.0")),
    "multiplier_student": float(env("PRICE_MULTIPLIER_STUDENT", "3.0")),
    "results_days": int(env("RESULTS_DAYS", "30")),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
