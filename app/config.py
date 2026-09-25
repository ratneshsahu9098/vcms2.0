import os

# Project root (parent of the app/ package). Runtime data lives in data/.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")


class Config:
    SECRET_KEY = os.environ.get("VCMS_SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "VCMS_DATABASE_URI", f"sqlite:///{os.path.join(DATA_DIR, 'vehicles.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session hardening + CSRF (see app/csrf.py); escape hatch: VCMS_CSRF_ENABLED=false
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_ENABLED = os.environ.get("VCMS_CSRF_ENABLED", "true").lower() == "true"

    UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
    EXPORT_FOLDER = os.path.join(DATA_DIR, "exports")
    BACKUP_FOLDER = os.path.join(DATA_DIR, "backups")
    SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
    IMPORT_CACHE_DIR = os.path.join(DATA_DIR, "import_cache")
    IMPORT_MAX_MB = 5
    INSIGHTS_CACHE = os.path.join(DATA_DIR, "insights_cache.json")
    ALLOWED_IMPORT_EXTENSIONS = {"xlsx", "xls", "csv", "json"}

    # Single-user login credentials (change in production / move to env vars)
    LOGIN_REQUIRED = os.environ.get("VCMS_LOGIN_REQUIRED", "true").lower() == "true"
    ADMIN_USERNAME = os.environ.get("VCMS_ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.environ.get("VCMS_ADMIN_PASSWORD", "admin123")

    # Reminder thresholds, in days before expiry
    REMINDER_WINDOWS = [30, 15, 7, 1]

    # AI provider settings ("openrouter" or "google")
    AI_PROVIDER = os.environ.get("VCMS_AI_PROVIDER", "openrouter")
    OPENROUTER_API_KEY = os.environ.get("VCMS_OPENROUTER_KEY", "")
    OPENROUTER_MODEL = os.environ.get("VCMS_OPENROUTER_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
    GOOGLE_API_KEY = os.environ.get("VCMS_GOOGLE_KEY", "")
    GOOGLE_MODEL = os.environ.get("VCMS_GOOGLE_MODEL", "gemini-2.5-flash")

    # Google Drive settings
    GDRIVE_ENABLED = os.environ.get("VCMS_GDRIVE_ENABLED", "false").lower() == "true"

    # Email reminder (SMTP) settings
    SMTP_SERVER = os.environ.get("VCMS_SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = os.environ.get("VCMS_SMTP_PORT", "587")
    SMTP_USER = os.environ.get("VCMS_SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("VCMS_SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("VCMS_SMTP_FROM", "")
    EMAIL_REMINDER_HOUR = int(os.environ.get("VCMS_EMAIL_REMINDER_HOUR", "9"))
