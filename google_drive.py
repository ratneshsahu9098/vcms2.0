import os
import json
import logging
from datetime import datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
FOLDER_NAME = "VCMS Backups"
MAX_BACKUPS = 10


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if creds and creds.valid:
            _save_token(creds)
            return creds
        return None
    return creds


def get_drive_service():
    creds = get_credentials()
    if not creds:
        return None
    return build("drive", "v3", credentials=creds)


def is_connected():
    creds = get_credentials()
    return creds is not None and creds.valid


def get_user_email():
    service = get_drive_service()
    if not service:
        return None
    try:
        about = service.about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress")
    except Exception:
        return None


def get_or_create_folder(service):
    query = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    file_metadata = {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
    file = service.files().create(body=file_metadata, fields="id").execute()
    return file.get("id")


def upload_backup(local_path):
    service = get_drive_service()
    if not service:
        return {"ok": False, "error": "Google Drive not connected"}

    try:
        folder_id = get_or_create_folder(service)
        filename = os.path.basename(local_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
            "description": f"VCMS Backup - {timestamp}",
        }
        media = MediaFileUpload(local_path, resumable=True)
        file = service.files().create(
            body=file_metadata, media_body=media, fields="id, name, size, createdTime"
        ).execute()

        delete_old_backups(service, folder_id)

        return {
            "ok": True,
            "file_id": file.get("id"),
            "name": file.get("name"),
            "size": int(file.get("size", 0)),
            "created": file.get("createdTime"),
        }
    except Exception as e:
        logger.exception("Google Drive upload failed")
        return {"ok": False, "error": str(e)}


def list_backups():
    service = get_drive_service()
    if not service:
        return []

    try:
        folder_id = get_or_create_folder(service)
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, size, createdTime)",
            orderBy="createdTime desc",
        ).execute()

        backups = []
        for f in results.get("files", []):
            size = int(f.get("size", 0))
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            created = f.get("createdTime", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created_str = dt.strftime("%d %b %Y, %I:%M %p")
                except Exception:
                    created_str = created
            else:
                created_str = "—"
            backups.append({
                "id": f.get("id"),
                "name": f.get("name"),
                "size": size_str,
                "created": created_str,
            })
        return backups
    except Exception:
        logger.exception("Failed to list Google Drive backups")
        return []


def download_backup(file_id, local_path):
    service = get_drive_service()
    if not service:
        return {"ok": False, "error": "Google Drive not connected"}

    try:
        from googleapiclient.http import MediaIoBaseDownload
        import io

        request = service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(local_path, "wb") as f:
            f.write(file.getvalue())

        return {"ok": True, "path": local_path}
    except Exception as e:
        logger.exception("Google Drive download failed")
        return {"ok": False, "error": str(e)}


def delete_file(file_id):
    service = get_drive_service()
    if not service:
        return False
    try:
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception:
        return False


def delete_old_backups(service=None, folder_id=None):
    if service is None:
        service = get_drive_service()
    if not service:
        return
    if folder_id is None:
        folder_id = get_or_create_folder(service)

    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query, fields="files(id, name, createdTime)", orderBy="createdTime desc"
    ).execute()
    files = results.get("files", [])

    if len(files) > MAX_BACKUPS:
        for f in files[MAX_BACKUPS:]:
            try:
                service.files().delete(fileId=f["id"]).execute()
            except Exception:
                pass


def _get_client_config():
    client_id = os.environ.get("VCMS_GDRIVE_CLIENT_ID", "")
    client_secret = os.environ.get("VCMS_GDRIVE_CLIENT_SECRET", "")
    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
    if os.path.exists(CLIENT_SECRET_FILE):
        with open(CLIENT_SECRET_FILE) as f:
            return json.load(f)
    return None


def start_oauth_flow(redirect_uri):
    config = _get_client_config()
    if not config:
        return None, "Google Drive credentials not found. Set VCMS_GDRIVE_CLIENT_ID/SECRET in .env or place client_secret.json."
    flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=redirect_uri)
    return flow, None


def save_token_from_code(code, redirect_uri):
    try:
        config = _get_client_config()
        if not config:
            return {"ok": False, "error": "Google Drive credentials not found."}
        flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        _save_token(creds)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def disconnect():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return True


def _save_token(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
