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
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.microsoft",
    "apps.accounts",
    "apps.jobs",
    "apps.compute",
    "apps.panel",
    "apps.legal",
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
    "allauth.account.middleware.AccountMiddleware",
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
LOGIN_REDIRECT_URL = "jobs:dashboard"
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
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = "\u202f"
NUMBER_GROUPING = 3

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

# E-mail: SMTP when configured (Brevo, EU), otherwise printed to the log
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 20
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST else "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "fdsrun <noreply@fdsrun.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMIN_EMAIL = env("ADMIN_EMAIL", "biuro@fp-solutions.pl")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Company details for invoices and legal pages (fill in before launch — docs/sekrety.md)
COMPANY = {
    # Dane z zaświadczenia CEIDG z 27.10.2026 (jawne); sekrety COMPANY_* mogą je nadpisać.
    "name": env("COMPANY_NAME", "Fire Protection Solutions Jakub Baran"),
    "address": env("COMPANY_ADDRESS", "ul. Grzybowa 7A/2, 05-825 Grodzisk Mazowiecki"),
    "nip": env("COMPANY_NIP", "6182094888"),
    "regon": env("COMPANY_REGON", "528892780"),
    "email": env("COMPANY_EMAIL", "biuro@fp-solutions.pl"),
    "phone": env("COMPANY_PHONE", "+48 790 782 993"),
    "www": env("COMPANY_WWW", "https://www.fp-solutions.pl/"),
}


# ----- social login (Google, GitHub, Microsoft) via django-allauth -----
# Our own views handle e-mail/password login and registration; allauth only adds the
# external providers. A provider appears on the login page only when its keys are set.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"  # our own confirmation flow covers e-mail/password accounts
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = False      # first external login asks for the account type
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_FORMS = {"signup": "apps.accounts.forms.SocialSignupForm"}
SOCIALACCOUNT_PROVIDERS = {
    "google": {"APPS": [{"client_id": env("GOOGLE_CLIENT_ID", ""), "secret": env("GOOGLE_CLIENT_SECRET", "")}], "SCOPE": ["profile", "email"], "AUTH_PARAMS": {"prompt": "select_account"}},
    "github": {"APPS": [{"client_id": env("GITHUB_CLIENT_ID", ""), "secret": env("GITHUB_CLIENT_SECRET", "")}], "SCOPE": ["user:email"]},
    "microsoft": {"APPS": [{"client_id": env("MS_CLIENT_ID", ""), "secret": env("MS_CLIENT_SECRET", ""), "settings": {"tenant": "common"}}]},
}
SOCIAL_PROVIDERS_ENABLED = [name for name, cfg in SOCIALACCOUNT_PROVIDERS.items() if cfg["APPS"][0]["client_id"]]
SOCIALACCOUNT_PROVIDERS = {name: cfg for name, cfg in SOCIALACCOUNT_PROVIDERS.items() if name in SOCIAL_PROVIDERS_ENABLED}


# ----- payments and invoicing (stage 3) -----
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
ING_API_KEY = env("ING_API_KEY", "")

# Student accounts get the student rate only once verified: automatically for an e-mail in
# an academic domain, otherwise by the admin in the panel.
STUDENT_DOMAINS = [d.strip().lower() for d in env("STUDENT_DOMAINS", ".edu.pl,.edu,.ac.uk,.ac.at,.ac.be,.ac.jp,.ac.nz,.edu.au,.uni-*.de,.tu-*.de,.ethz.ch,.epfl.ch,.tudelft.nl,.kth.se,.dtu.dk,.aalto.fi,.ntnu.no,.cvut.cz,.vutbr.cz,.polimi.it,.upm.es,.upc.edu").split(",") if d.strip()]
