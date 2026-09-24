import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("VCMS_SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "VCMS_DATABASE_URI", f"sqlite:///{os.path.join(BASE_DIR, 'vehicles.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    EXPORT_FOLDER = os.path.join(BASE_DIR, "exports")
    BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
    ALLOWED_IMPORT_EXTENSIONS = {"xlsx", "xls", "csv", "json"}

    # Single-user login credentials (change in production / move to env vars)
    LOGIN_REQUIRED = os.environ.get("VCMS_LOGIN_REQUIRED", "true").lower() == "true"
    ADMIN_USERNAME = os.environ.get("VCMS_ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.environ.get("VCMS_ADMIN_PASSWORD", "admin123")

    # Reminder thresholds, in days before expiry
    REMINDER_WINDOWS = [30, 15, 7, 1]

    # OpenRouter AI settings
    OPENROUTER_API_KEY = os.environ.get("VCMS_OPENROUTER_KEY", "")
    OPENROUTER_MODEL = os.environ.get("VCMS_OPENROUTER_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")

    # Google Gemini AI settings
    GEMINI_API_KEY = os.environ.get("VCMS_GEMINI_KEY", "")
    GEMINI_MODEL = os.environ.get("VCMS_GEMINI_MODEL", "gemini-2.0-flash")
    AI_PROVIDER = os.environ.get("VCMS_AI_PROVIDER", "openrouter")

    # Google Drive settings
    GDRIVE_ENABLED = os.environ.get("VCMS_GDRIVE_ENABLED", "false").lower() == "true"

    # Email reminder settings
    SMTP_SERVER = os.environ.get("VCMS_SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("VCMS_SMTP_PORT", "587"))
    EMAIL_REMINDERS_ENABLED = os.environ.get("VCMS_EMAIL_REMINDERS_ENABLED", "false").lower() == "true"
    EMAIL_REMINDER_HOUR = int(os.environ.get("VCMS_EMAIL_REMINDER_HOUR", "9"))
