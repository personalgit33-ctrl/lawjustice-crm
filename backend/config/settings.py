"""Law & Justice CRM — настройки Django.

Все секреты и адреса — из переменных окружения (.env.example).
Без переменных проект стартует в режиме разработки: SQLite, in-memory WebSocket, задачи синхронно.
"""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "apps.accounts",
    "apps.audit",
    "apps.crm",
    "apps.boards",
    "apps.comms",
    "apps.assistant",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"), conn_max_age=60
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = env("TIME_ZONE", "Asia/Bishkek")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(env("MEDIA_ROOT", BASE_DIR / "media"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Файлы: локально (dev) или S3-совместимое хранилище (prod) — см. apps/crm/storage.py
S3_BUCKET = env("S3_BUCKET")
S3_ENDPOINT = env("S3_ENDPOINT")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
if S3_BUCKET:
    # приватный бакет; файлы отдаются только через /api/files/<id>/?sig=… (подписанные ссылки)
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {"bucket_name": S3_BUCKET, "endpoint_url": S3_ENDPOINT, "default_acl": "private", "querystring_auth": True, "file_overwrite": False},
    }
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", 50))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "apps.accounts.exceptions.handler",
    "DEFAULT_THROTTLE_RATES": {"login": env("LOGIN_RATE", "10/min")},
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MIN", 30))),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=int(env("JWT_REFRESH_HOURS", 12))),
    "ROTATE_REFRESH_TOKENS": False,
}

CORS_ALLOWED_ORIGINS = [o for o in env("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o]
# превью-деплои Vercel: https://<проект>-<хэш>-<команда>.vercel.app
CORS_ALLOWED_ORIGIN_REGEXES = [r for r in env("CORS_ALLOWED_ORIGIN_REGEXES", "").split(",") if r]
CORS_ALLOW_ALL_ORIGINS = DEBUG

REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_TASK_ALWAYS_EAGER = not bool(REDIS_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "deadline-reminders": {"task": "apps.crm.tasks.deadline_reminders", "schedule": 15 * 60},
    "stale-items": {"task": "apps.crm.tasks.stale_report", "schedule": 24 * 3600},
    "recordings-retention": {"task": "apps.comms.tasks.recordings_retention", "schedule": 24 * 3600},
    "first-response-sla": {"task": "apps.comms.tasks.first_response_sla", "schedule": 5 * 60},
}

# Интеграции
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = env("WHATSAPP_PHONE_ID")
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", "lj-verify")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET")
META_PAGE_TOKEN = env("META_PAGE_TOKEN")
META_VERIFY_TOKEN = env("META_VERIFY_TOKEN", "lj-verify")
GOOGLE_WEBHOOK_KEY = env("GOOGLE_WEBHOOK_KEY", "lj-google-key")
TELEPHONY_WEBHOOK_KEY = env("TELEPHONY_WEBHOOK_KEY", "lj-tel-key")
TELEPHONY_API_URL = env("TELEPHONY_API_URL")
TELEPHONY_API_TOKEN = env("TELEPHONY_API_TOKEN")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-4-5")
PRIVACY_URL = env("PRIVACY_URL", "lawjustice.kg/privacy")

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", 587))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "crm@lawjustice.kg")

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
