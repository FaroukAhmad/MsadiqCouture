import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


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
            raise RuntimeError(
                "DATABASE_URL is not set. Add a hosted Postgres database "
                "(e.g. Neon via the Vercel Marketplace) and set DATABASE_URL "
                "in Project Settings > Environment Variables."
            )
        # Local development only: make sure the folder for the SQLite file exists.
        (BASE_DIR / "instance").mkdir(exist_ok=True)
        return f"sqlite:///{BASE_DIR / 'instance' / 'msadiq.db'}"
    return url.replace("postgres://", "postgresql://", 1)


class Config:
    ENVIRONMENT = os.environ.get("ENVIRONMENT") or ("production" if ON_VERCEL else "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    # Demo seeding creates well-known logins (admin123 etc.), so it only runs by
    # default against the local SQLite fallback - never on Vercel or when a
    # DATABASE_URL is configured. Set SEED_DEMO_DATA=1 to force it.
    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "0" if (ON_VERCEL or DATABASE_URL) else "1") == "1"
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
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
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@msadiqcouture.com")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
