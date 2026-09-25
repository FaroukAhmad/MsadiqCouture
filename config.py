import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _int_env(name, default):
    """Read an int env var, tolerating unset OR empty-string values.

    Vercel (and copy-pasted .env files) can leave a variable present but
    blank, and int("") raises ValueError, which crashes the app at import
    time. Treat blank the same as unset.
    """
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


BASE_DIR = Path(__file__).resolve().parent
# Vercel sets VERCEL=1 at build and runtime. Its filesystem is read-only
# (except /tmp) and every request may run on a fresh instance, so the app
# needs a hosted database there instead of a local SQLite file.
ON_VERCEL = bool(os.environ.get("VERCEL"))

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _database_uri():
    url = DATABASE_URL
    if not url:
        if ON_VERCEL:
            # Don't raise here — a RuntimeError at class-definition time
            # crashes the Vercel cold-start before any request is handled,
            # producing a 500 with no useful message. Return a placeholder
            # so the module imports cleanly; every DB-backed route will
            # still fail with a clear OperationalError that appears in logs.
            import logging
            logging.getLogger(__name__).error(
                "DATABASE_URL is not set on Vercel. "
                "Add a Postgres database in Project Settings > Environment Variables."
            )
            return "sqlite:////tmp/msadiq-placeholder.db"
        # Local development only: make sure the folder for the SQLite file exists.
        (BASE_DIR / "instance").mkdir(exist_ok=True)
        return f"sqlite:///{BASE_DIR / 'instance' / 'msadiq.db'}"
    return url.replace("postgres://", "postgresql://", 1).replace(
        "postgresql+psycopg://", "postgresql+psycopg2://", 1
    )


class Config:
    ON_VERCEL = ON_VERCEL
    ENVIRONMENT = os.environ.get("ENVIRONMENT") or ("production" if ON_VERCEL else "development")
    # `or` (not a dict default) so a variable that exists but is blank is
    # treated the same as missing, instead of silently becoming "".
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    # Demo seeding creates well-known logins (admin123 etc.), so it only runs by
    # default against the local SQLite fallback - never on Vercel or when a
    # DATABASE_URL is configured. Set SEED_DEMO_DATA=1 to force it.
    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "0" if (ON_VERCEL or DATABASE_URL) else "1") == "1"
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = _int_env("MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        "/tmp/uploads" if ON_VERCEL else str(BASE_DIR / "public" / "static" / "uploads"),
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1" if ON_VERCEL else "0") == "1"
    PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
    PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
    PAYSTACK_CALLBACK_URL = os.environ.get("PAYSTACK_CALLBACK_URL", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = _int_env("SMTP_PORT", 587)
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@msadiqcouture.com")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
