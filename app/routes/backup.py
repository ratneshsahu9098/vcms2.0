"""Local backup/restore and Google Drive sync routes."""
from datetime import datetime
import os
import re

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for)
from werkzeug.utils import secure_filename

from app.extensions import db
from app.middleware import login_required
from app.services import google_drive
from app.utils import (create_backup, list_backups, restore_backup)

bp = Blueprint("backup", __name__)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_backup_path(name):
    """Resolve a backup filename inside BACKUP_FOLDER, or None if unsafe."""
    if not name or not _SAFE_NAME_RE.match(name):
        return None
    folder = os.path.realpath(current_app.config["BACKUP_FOLDER"])
    path = os.path.realpath(os.path.join(folder, name))
    if not path.startswith(folder + os.sep):
        return None
    return path

# ---- Backup / Restore -------------------------------------------------

@bp.route("/backup", methods=["GET", "POST"])
@login_required
def backup():
    db_path = current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name, _ = create_backup(db_path, current_app.config["BACKUP_FOLDER"])
            flash(f"Backup created: {name} (database + settings, API keys and models)", "success")
        elif action == "restore":
            backup_name = request.form.get("backup_name")
            backup_path = _safe_backup_path(backup_name)
            if backup_path and os.path.exists(backup_path):
                db.session.remove()
                db.engine.dispose()
                result = restore_backup(backup_path, db_path)
                if result["ok"]:
                    flash(f"{result['message']} ({backup_name})", "success")
                else:
                    flash(result["message"], "error")
            else:
                flash("Backup file not found.", "error")
        elif action == "upload_restore":
            file = request.files.get("backup_file")
            if file and file.filename:
                filename = secure_filename(file.filename.strip())
                if not filename.endswith(".db") and not filename.endswith(".zip"):
                    flash("Only .db or .zip backup files are allowed.", "error")
                else:
                    upload_path = os.path.join(current_app.config["BACKUP_FOLDER"], f"upload_{filename}")
                    file.save(upload_path)
                    db.session.remove()
                    db.engine.dispose()
                    result = restore_backup(upload_path, db_path)
                    os.remove(upload_path)
                    if result["ok"]:
                        flash(f"{result['message']} (uploaded: {filename})", "success")
                    else:
                        flash(result["message"], "error")
            else:
                flash("No file selected.", "error")
        return redirect(url_for("backup.backup"))

    from app.utils import load_settings
    backups = list_backups(current_app.config["BACKUP_FOLDER"])
    gdrive_backups = google_drive.list_backups()
    gdrive_connected = google_drive.is_connected()
    app_settings = load_settings()
    return render_template("backup.html", backups=backups,
                           gdrive_backups=gdrive_backups, gdrive_connected=gdrive_connected,
                           app_settings=app_settings)

@bp.route("/backup/download/<name>")
@login_required
def download_backup(name):
    path = _safe_backup_path(name)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)

# ---- Google Drive Sync ------------------------------------------------

@bp.route("/settings/google/connect")
@login_required
def gdrive_connect():
    flow, error = google_drive.start_oauth_flow()
    if error:
        flash(error, "error")
        return redirect(url_for("settings.settings"))
    redirect_uri = url_for("backup.gdrive_callback", _external=True)
    auth_url, _ = flow.authorization_url(prompt="consent", redirect_uri=redirect_uri)
    return redirect(auth_url)

@bp.route("/settings/google/callback")
def gdrive_callback():
    from app.utils import load_settings, save_settings
    code = request.args.get("code")
    if not code:
        flash("Google Drive authorization failed.", "error")
        return redirect(url_for("settings.settings"))
    redirect_uri = url_for("backup.gdrive_callback", _external=True)
    result = google_drive.save_token_from_code(code, redirect_uri)
    if result.get("ok"):
        email = google_drive.get_user_email()
        settings = load_settings()
        settings["gdrive_user_email"] = email or ""
        save_settings(settings)
        flash(f"Google Drive connected as {email or 'unknown'}", "success")
    else:
        flash(f"Google Drive connection failed: {result.get('error', 'Unknown error')}", "error")
    return redirect(url_for("settings.settings"))

@bp.route("/settings/google/disconnect", methods=["POST"])
@login_required
def gdrive_disconnect():
    from app.utils import load_settings, save_settings
    google_drive.disconnect()
    settings = load_settings()
    settings["gdrive_user_email"] = ""
    settings["gdrive_last_sync"] = ""
    settings["gdrive_last_sync_status"] = ""
    save_settings(settings)
    flash("Google Drive disconnected.", "success")
    return redirect(url_for("settings.settings"))

@bp.route("/backup/sync", methods=["POST"])
@login_required
def gdrive_sync():
    from app.utils import load_settings, save_settings
    db_path = current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    name, backup_path = create_backup(db_path, current_app.config["BACKUP_FOLDER"])
    result = google_drive.upload_backup(backup_path)
    settings = load_settings()
    if result.get("ok"):
        settings["gdrive_last_sync"] = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
        settings["gdrive_last_sync_status"] = "success"
        save_settings(settings)
        flash(f"Synced to Google Drive: {name}", "success")
    else:
        settings["gdrive_last_sync_status"] = f"error: {result.get('error', 'unknown')}"
        save_settings(settings)
        flash(f"Google Drive sync failed: {result.get('error', 'Unknown')}", "error")
    return redirect(url_for("backup.backup"))

@bp.route("/backup/gdrive-list")
@login_required
def gdrive_list():
    backups = google_drive.list_backups()
    return jsonify(backups)

@bp.route("/backup/gdrive-restore", methods=["POST"])
@login_required
def gdrive_restore():
    file_id = request.form.get("file_id")
    if not file_id:
        flash("No backup selected.", "error")
        return redirect(url_for("backup.backup"))
    db_path = current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    temp_path = os.path.join(current_app.config["BACKUP_FOLDER"], "gdrive_restore_temp.bak")
    dl = google_drive.download_backup(file_id, temp_path)
    if dl.get("ok"):
        db.session.remove()
        db.engine.dispose()
        result = restore_backup(temp_path, db_path)
        os.remove(temp_path)
        if result["ok"]:
            flash(f"{result['message']} (Google Drive)", "success")
        else:
            flash(result["message"], "error")
    else:
        flash(f"Restore failed: {dl.get('error', 'Unknown')}", "error")
    return redirect(url_for("backup.backup"))

@bp.route("/backup/sync-status")
@login_required
def gdrive_sync_status():
    from app.utils import load_settings
    settings = load_settings()
    connected = google_drive.is_connected()
    return jsonify({
        "connected": connected,
        "email": settings.get("gdrive_user_email", ""),
        "last_sync": settings.get("gdrive_last_sync", ""),
        "last_status": settings.get("gdrive_last_sync_status", ""),
        "auto_sync": settings.get("gdrive_auto_sync", True),
    })


