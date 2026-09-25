"""App-wide request hooks.

Auto-syncs a backup to Google Drive after successful POSTs that mutate data.
"""
import logging
import threading
from datetime import datetime

from flask import request

from app.services import google_drive
from app.utils import create_backup, load_settings, save_settings

logger = logging.getLogger(__name__)

# Endpoints whose successful POSTs mean fleet data changed.
GDRIVE_SYNC_ENDPOINTS = (
    "vehicles.add_vehicle",
    "vehicles.edit_vehicle",
    "vehicles.delete_vehicle",
    "vehicles.delete_all_vehicles",
    "data.import_excel",
    "backup.backup",
)


def _sync_to_gdrive(app):
    settings = load_settings()
    if not settings.get("gdrive_auto_sync", True):
        return
    if not google_drive.is_connected():
        return
    try:
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
        name, backup_path = create_backup(db_path, app.config["BACKUP_FOLDER"])
        result = google_drive.upload_backup(backup_path)
        settings = load_settings()
        if result.get("ok"):
            settings["gdrive_last_sync"] = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
            settings["gdrive_last_sync_status"] = "success"
        else:
            settings["gdrive_last_sync_status"] = f"error: {result.get('error', '')}"
        save_settings(settings)
    except Exception:
        logger.exception("Auto-sync to Google Drive failed")


def register_hooks(app):
    @app.after_request
    def auto_gdrive_sync(response):
        if request.method == "POST" and response.status_code < 400:
            if request.endpoint in GDRIVE_SYNC_ENDPOINTS:
                threading.Thread(target=_sync_to_gdrive, args=(app,), daemon=True).start()
        return response
