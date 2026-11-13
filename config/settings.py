"""
Django settings for LevelUp Gear — B2C gaming-gear e-commerce (CO3027 assignment).

All secrets and environment-specific values are read from environment
variables (see .env.example). Defaults are safe for local development only.
"""
import hashlib
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)

# Django admin lives at a path that is hard to guess. Set DJANGO_ADMIN_URL to choose one; otherwise it is
# derived from the secret key (stable per deployment, different on every deployment). Staff reach it from
# the "Django Admin" link in the dashboard; the path is also printed by `manage.py seed_demo`.
ADMIN_URL = os.getenv("DJANGO_ADMIN_URL", "").strip("/") or (
    "he-thong-" + hmac.new(SECRET_KEY.encode(), b"admin-url", hashlib.sha256).hexdigest()[:12]
)
ADMIN_URL += "/"
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")
# Render sets this to the service's public hostname, so a renamed service still works without editing env vars
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

# Client IP behind a reverse proxy (order log, login lockout, lookup rate limit, payment gateway).
# X-Forwarded-For is only trusted for the last TRUSTED_PROXY_COUNT hops: each proxy appends the address it
# saw, while anything further left was sent by the client and can be forged. CLIENT_IP_HEADER names a header
# that the edge proxy always overwrites (e.g. CF-Connecting-IP); it wins when present.
# Both empty / 0 (default, no proxy): REMOTE_ADDR.
CLIENT_IP_HEADER = os.getenv("CLIENT_IP_HEADER", "").strip()
TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0") or 0)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    # Project apps
    "apps.accounts",
    "apps.catalog",
    "apps.cart",
    "apps.orders",
    "apps.payments",
    "apps.recommendations",
    "apps.chatbot",
    "apps.dashboard",
    "apps.pages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "apps.recommendations.middleware.VisitTrackingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.cart.context_processors.cart",
                "apps.catalog.context_processors.navigation",
                "config.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------- Database
# SQLite by default; set DATABASE_URL=postgres://user:pass@host:5432/db for Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres"):
    from urllib.parse import urlparse

    u = urlparse(DATABASE_URL)
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
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrUsernameBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "pages:home"
LOGOUT_REDIRECT_URL = "pages:home"

# ---------------------------------------------------------------- i18n
LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

# ---------------------------------------------------------------- Static / media
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
# "database" keeps uploads in PostgreSQL — for hosts whose disk is wiped on each deploy (Render free tier).
MEDIA_STORAGE = os.getenv("MEDIA_STORAGE", "filesystem").lower()
STORAGES = {
    "default": {
        "BACKEND": "apps.pages.storage.DatabaseStorage"
        if MEDIA_STORAGE == "database"
        else "django.core.files.storage.FileSystemStorage"
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
SERVE_MEDIA = env_bool("SERVE_MEDIA", True)  # demo hosting serves uploads from Django

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- Sessions & cache
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ---------------------------------------------------------------- Production hardening
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    # Secure-only cookies & HSTS only make sense when the site is served over
    # HTTPS. A local "production-like" run over plain HTTP (docker compose)
    # sets DJANGO_SSL_REDIRECT=False; with Secure cookies the browser would
    # drop the CSRF cookie there and every form POST would fail with 403.
    HTTPS_ENABLED = env_bool("DJANGO_HTTPS", SECURE_SSL_REDIRECT)
    SESSION_COOKIE_SECURE = HTTPS_ENABLED
    CSRF_COOKIE_SECURE = HTTPS_ENABLED
    if HTTPS_ENABLED:
        SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------- Email
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "LevelUp Gear <no-reply@levelupgear.vn>")

# ---------------------------------------------------------------- Business configuration
SITE_NAME = "LevelUp Gear"
SITE_URL = os.getenv("SITE_URL") or (f"https://{RENDER_EXTERNAL_HOSTNAME}" if RENDER_EXTERNAL_HOSTNAME else "http://127.0.0.1:8000")
# Seller identity shown in footer — required by the E-commerce Law 122/2025/QH15 (in force 1/7/2026)
BUSINESS_INFO = {
    "legal_name": "Công ty TNHH LevelUp Gear Việt Nam",
    "tax_code": "0300000000 (mã số demo)",
    "address": "268 Lý Thường Kiệt, Phường Diên Hồng, TP. Hồ Chí Minh",
    "hotline": "1900 0000",
    "email": "support@levelupgear.vn",
    "registration": "Website đang thông báo với Bộ Công Thương (online.gov.vn) — demo học thuật",
}
FREE_SHIPPING_THRESHOLD = 1_000_000  # VND
VAT_RATE = 0.10  # prices are VAT-inclusive; rate used to display tax breakdown
LOW_STOCK_THRESHOLD = 5
# Unpaid VNPay/MoMo orders are auto-cancelled after this many minutes
# (VNPay payment links themselves expire after 15 minutes).
UNPAID_ORDER_TIMEOUT_MINUTES = int(os.getenv("UNPAID_ORDER_TIMEOUT_MINUTES", "60"))
# Receiving account for bank transfers. The QR follows the NAPAS VietQR
# (EMVCo) standard, so any Vietnamese banking app can scan it.
BANK_TRANSFER = {
    "bank": os.getenv("BANK_NAME", "Vietcombank"),
    "bin": os.getenv("BANK_BIN", "970436"),
    "account_no": os.getenv("BANK_ACCOUNT_NO", "0001234567890"),
    "account_name": os.getenv("BANK_ACCOUNT_NAME", "CONG TY TNHH LEVELUP GEAR VIET NAM"),
}

# ---------------------------------------------------------------- Payments
# PAYMENT_MODE: "mock" (built-in simulated gateway, default) or "vnpay" (VNPay sandbox).
PAYMENT_MODE = os.getenv("PAYMENT_MODE", "mock")
VNPAY = {
    "TMN_CODE": os.getenv("VNPAY_TMN_CODE", ""),
    "HASH_SECRET": os.getenv("VNPAY_HASH_SECRET", ""),
    "PAYMENT_URL": os.getenv("VNPAY_PAYMENT_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"),
}
# Secret used to sign the simulated gateway's callbacks (HMAC-SHA512, same scheme as VNPay)
MOCK_GATEWAY_SECRET = os.getenv("MOCK_GATEWAY_SECRET", "mock-gateway-secret-change-me")
# The simulated gateway marks an order "paid" without any money moving, so it is
# only enabled by default on a developer machine (DEBUG=True). A public *demo*
# deployment may opt in with ALLOW_MOCK_PAYMENTS=True (+ a strong MOCK_GATEWAY_SECRET);
# a real shop must leave it off. When off: MoMo is hidden (no real integration yet),
# VNPay is offered only with real merchant keys, and mock callbacks are rejected.
ALLOW_MOCK_PAYMENTS = env_bool("ALLOW_MOCK_PAYMENTS", DEBUG)

from config.secrets_check import insecure_settings  # noqa: E402

_problems = insecure_settings(
    debug=DEBUG, secret_key=SECRET_KEY, allow_mock_payments=ALLOW_MOCK_PAYMENTS, mock_gateway_secret=MOCK_GATEWAY_SECRET
)
if _problems:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Insecure production settings:\n- " + "\n- ".join(_problems))

# ---------------------------------------------------------------- Chatbot (optional LLM)
# If GEMINI_API_KEY is set the chatbot can answer free-form questions with an LLM;
# otherwise it uses the built-in intent + product-search engine (fully offline).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO"},
        "security": {"handlers": ["console"], "level": "WARNING"},
    },
}
