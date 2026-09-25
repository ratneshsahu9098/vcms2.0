import json
import os

from app.config import Config

SETTINGS_FILE = Config.SETTINGS_FILE

DEFAULT_SETTINGS = {
    "ai_provider": "openrouter",
    "openrouter_api_key": "",
    "openrouter_model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
    "google_api_key": "",
    "google_model": "gemini-2.5-flash",
    "smtp_server": "smtp.gmail.com",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "email_reminders_enabled": True,
    "auto_reminders_enabled": False,
    "auto_reminder_windows": [7, 3, 0],
    "gdrive_auto_sync": True,
    "gdrive_last_sync": "",
    "gdrive_last_sync_status": "",
    "gdrive_user_email": "",
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            saved = json.load(f)
            settings = dict(DEFAULT_SETTINGS)
            settings.update(saved)
            return settings
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
