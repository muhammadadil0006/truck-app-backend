"""
Single env-driven settings file — no base/local/production split. Env vars
are the only thing that differs between local dev and the Vercel deployment,
so a settings package would be over-architecture for this project's scale.
See backend/README.md for the full list of environment variables.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")  # no-op if absent; production injects real env vars directly

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Vercel terminates TLS and forwards the original scheme via this header —
# without it Django thinks every request is plain HTTP behind the proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    # Supabase's connection pooler runs pgbouncer in transaction mode, which
    # recycles the underlying server connection between transactions — a
    # psycopg3 server-side prepared statement from one transaction can vanish
    # before the next one reuses that connection. prepare_threshold=None
    # disables server-side prepare entirely so this never bites.
    DATABASES["default"]["OPTIONS"] = {
        "sslmode": "require",
        "prepare_threshold": None,
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Project-specific settings ---

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    # DRF's DecimalField serializes as a JSON string ("10.00") by default.
    # The frontend's Trip/DailyLog types declare these fields as `number`
    # and does real arithmetic on them (e.g. driving_hours + on_duty_hours
    # for "on-duty hours today") — string values there silently concatenate
    # instead of adding. Coerce to real JSON numbers app-wide instead of
    # patching every consumer.
    "COERCE_DECIMAL_TO_STRING": False,
}

# Repeated identical geocode/directions lookups are cached here (see
# services/routing/client.py) instead of reaching for Redis — this is a
# single-process deployment with no need for a shared external cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

ORS_API_KEY = env("ORS_API_KEY", default="")
ORS_BASE_URL = env("ORS_BASE_URL", default="https://api.openrouteservice.org")
