import os
import shutil
import zipfile
from datetime import datetime

from app.config import Config


def create_backup(db_path, backup_folder):
    """Create a full backup archive: database + settings.json
    (settings.json carries API keys, AI model, SMTP and reminder config)."""
    os.makedirs(backup_folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    backup_name = f"backup_{timestamp}.zip"
    backup_path = os.path.join(backup_folder, backup_name)
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, "vehicles.db")
        if os.path.exists(Config.SETTINGS_FILE):
            zf.write(Config.SETTINGS_FILE, "settings.json")
    return backup_name, backup_path


def restore_backup(backup_path, db_path):
    """Restore from a full .zip backup (database + settings) or a legacy
    plain .db backup (database only). Returns {"ok", "kind", "message"}."""
    if not os.path.exists(backup_path):
        return {"ok": False, "kind": None, "message": "Backup file not found."}

    if zipfile.is_zipfile(backup_path):
        with zipfile.ZipFile(backup_path, "r") as zf:
            names = zf.namelist()
            if "vehicles.db" not in names:
                return {"ok": False, "kind": None,
                        "message": "Backup archive is missing vehicles.db."}
            tmp_db = backup_path + ".tmpdb"
            try:
                with zf.open("vehicles.db") as src, open(tmp_db, "wb") as out:
                    shutil.copyfileobj(src, out)
                shutil.copy2(tmp_db, db_path)
            finally:
                if os.path.exists(tmp_db):
                    os.remove(tmp_db)
            settings_restored = False
            if "settings.json" in names:
                tmp_settings = backup_path + ".tmpsettings"
                try:
                    with zf.open("settings.json") as src, open(tmp_settings, "wb") as out:
                        shutil.copyfileobj(src, out)
                    shutil.copy2(tmp_settings, Config.SETTINGS_FILE)
                    settings_restored = True
                finally:
                    if os.path.exists(tmp_settings):
                        os.remove(tmp_settings)
        if settings_restored:
            return {"ok": True, "kind": "full",
                    "message": "Database and settings (API keys, models, SMTP) restored."}
        return {"ok": True, "kind": "db_only",
                "message": "Database restored (archive contained no settings.json)."}

    # Legacy plain .db backup: database only
    shutil.copy2(backup_path, db_path)
    return {"ok": True, "kind": "db_only",
            "message": "Database restored (legacy backup, settings kept as-is)."}


def list_backups(backup_folder):
    if not os.path.isdir(backup_folder):
        return []
    files = [f for f in os.listdir(backup_folder)
             if f.endswith(".db") or f.endswith(".zip")]
    backups = []
    for f in files:
        path = os.path.join(backup_folder, f)
        stat = os.stat(path)
        size = stat.st_size
        if size >= 1024 * 1024:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        elif size >= 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size} B"
        created = datetime.fromtimestamp(stat.st_mtime)
        backups.append({
            "name": f,
            "created": created.strftime("%d %b %Y, %I:%M %p"),
            "size": size_str,
        })
    backups.sort(key=lambda x: x["name"], reverse=True)
    return backups
