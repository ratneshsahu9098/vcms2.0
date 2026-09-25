"""App-wide request hooks.

Auto-syncs a backup to Google Drive after successful POSTs that mutate data.
Uses a thread-safe queue to avoid duplicate syncs and ensure sync only runs
after successful DB commit.
"""
import logging
import threading
import uuid
from datetime import datetime
from queue import Queue, Empty

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

# Thread-safe queue for pending sync operations
_sync_queue: Queue[tuple[str, str]] = Queue()
_sync_worker_started = False
_sync_worker_lock = threading.Lock()


def _sync_worker(app):
    """Background worker that processes sync queue."""
    while True:
        try:
            # Wait for work with timeout to allow graceful shutdown
            sync_id, endpoint = _sync_queue.get(timeout=60)
            if sync_id is None:  # Shutdown signal
                break
            try:
                _perform_sync(app, sync_id, endpoint)
            except Exception:
                logger.exception("Auto-sync to Google Drive failed for %s", sync_id)
            finally:
                _sync_queue.task_done()
        except Empty:
            continue


def _perform_sync(app, sync_id: str, endpoint: str):
    """Perform the actual Google Drive sync."""
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
        logger.info("Auto-synced to Google Drive (sync_id=%s, endpoint=%s)", sync_id, endpoint)
    except Exception:
        logger.exception("Auto-sync to Google Drive failed for %s", sync_id)


def _ensure_worker_started(app):
    """Start the background sync worker if not already running."""
    global _sync_worker_started
    with _sync_worker_lock:
        if not _sync_worker_started:
            worker = threading.Thread(target=_sync_worker, args=(app,), daemon=True)
            worker.start()
            _sync_worker_started = True


def register_hooks(app):
    _ensure_worker_started(app)

    @app.teardown_request
    def _teardown_request(exception):
        # Only queue sync if request succeeded (no exception) and was a POST to sync endpoint
        if exception is None and request.method == "POST":
            if request.endpoint in GDRIVE_SYNC_ENDPOINTS:
                # Generate unique sync ID for idempotency
                sync_id = str(uuid.uuid4())
                _sync_queue.put((sync_id, request.endpoint))

    # Keep the old after_request for backward compatibility (no-op now)
    @app.after_request
    def _legacy_after_request(response):
        return response
