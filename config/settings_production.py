import os
from django.core.exceptions import ImproperlyConfigured
from .settings_base import *  # noqa: F401,F403

DEBUG = False
if SECRET_KEY == "unsafe-development-key-change-me":
    raise ImproperlyConfigured("Set a secure SECRET_KEY in .env.")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set ALLOWED_HOSTS in .env.")
if not os.getenv("DB_NAME"):
    raise ImproperlyConfigured("Set PostgreSQL DB_NAME and credentials in .env.")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ["DB_NAME"],
    "USER": os.getenv("DB_USER", ""),
    "PASSWORD": os.getenv("DB_PASSWORD", ""),
    "HOST": os.getenv("DB_HOST", "127.0.0.1"),
    "PORT": os.getenv("DB_PORT", "5432"),
    "CONN_MAX_AGE": 60,
}}
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
