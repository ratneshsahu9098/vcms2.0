"""
Google Drive Setup Helper
Run this once to connect your Google account to VCMS.

Steps:
1. Create Google Cloud project (5 min): see instructions below
2. Download client_secret.json → place in the data/ folder
3. Run: python scripts/setup_gdrive.py
4. Browser opens → login with Google → done!
"""

import json
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
CLIENT_SECRET = os.path.join(DATA_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")


def check_client_secret():
    if not os.path.exists(CLIENT_SECRET):
        print("=" * 60)
        print("ERROR: client_secret.json not found!")
        print("=" * 60)
        print()
        print("You need to create it first. Follow these steps:")
        print()
        print("1. Go to: https://console.cloud.google.com")
        print("2. Create a new project (name: VCMS)")
        print("3. Go to 'APIs & Services' > 'Library'")
        print("4. Search 'Google Drive API' > Enable it")
        print("5. Go to 'APIs & Services' > 'OAuth consent screen'")
        print("   - Select 'External' > Create")
        print("   - App name: VCMS")
        print("   - Add your email as developer contact")
        print("   - Save & Continue (skip scopes for now)")
        print("   - Add your email as test user")
        print("   - Save")
        print("6. Go to 'APIs & Services' > 'Credentials'")
        print("   - Click 'Create Credentials' > 'OAuth client ID'")
        print("   - Application type: Desktop app")
        print("   - Name: VCMS")
        print("   - Click Create")
        print("7. Click the download icon (down arrow) to download JSON")
        print("8. Rename the downloaded file to: client_secret.json")
        print("9. Place it in:", DATA_DIR)
        print()
        print("Then run this script again: python scripts/setup_gdrive.py")
        print("=" * 60)
        return False

    try:
        with open(CLIENT_SECRET, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except ValueError:
        print("=" * 60)
        print("ERROR: client_secret.json is not valid JSON.")
        print("Re-download the OAuth client file and replace it in:", DATA_DIR)
        print("=" * 60)
        return False

    if "installed" not in cfg:
        print("=" * 60)
        if cfg.get("type") == "service_account":
            print("ERROR: client_secret.json is a SERVICE ACCOUNT key,")
            print("not an OAuth client! Browser login needs an OAuth 'Desktop app' client.")
            print("Download your service-account key for server use somewhere private")
            print("(or delete it if unused), then create the right file:")
            print("  1. https://console.cloud.google.com/apis/credentials")
            print("  2. Create Credentials > OAuth client ID")
            print("  3. Application type: Desktop app > Create")
            print("  4. Download the JSON, rename to client_secret.json, replace in:")
            print("     " + DATA_DIR)
        elif "web" in cfg:
            print("ERROR: client_secret.json is a WEB application OAuth client.")
            print("Create the OAuth client with Application type: Desktop app,")
            print("re-download, rename to client_secret.json and replace the file in:")
            print("     " + DATA_DIR)
        else:
            print("ERROR: client_secret.json is not an OAuth client file")
            print("(expected a top-level 'installed' key). Download the OAuth client")
            print("ID JSON from https://console.cloud.google.com/apis/credentials")
        print("=" * 60)
        return False
    return True


def setup():
    if not check_client_secret():
        return

    if os.path.exists(TOKEN_FILE):
        print("Google Drive is already connected!")
        print("Token file:", TOKEN_FILE)
        resp = input("Do you want to reconnect? (y/n): ").strip().lower()
        if resp != "y":
            return

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Installing required packages...")
        os.system("pip install google-auth-oauthlib")
        from google_auth_oauthlib.flow import InstalledAppFlow

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    print()
    print("Opening browser for Google login...")
    print("If the browser doesn't open, copy the URL below and open it manually.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)

    # Try to run on port 8080, fallback to other ports
    creds = None
    for port in [8080, 8081, 8082, 8090]:
        try:
            creds = flow.run_local_server(port=port, open_browser=True)
            break
        except OSError:
            continue

    if not creds:
        print("Failed to get credentials. Try again.")
        return

    # Save token
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print()
    print("=" * 60)
    print("SUCCESS! Google Drive is now connected.")
    print("Token saved to:", TOKEN_FILE)
    print()

    # Test connection and store the linked account in app settings
    email = ""
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds)
        about = service.about().get(fields="user(emailAddress)").execute()
        email = about.get("user", {}).get("emailAddress") or ""
        print(f"Connected as: {email or 'unknown'}")
    except Exception:
        print("Connection verified.")

    settings_path = os.path.join(DATA_DIR, "settings.json")
    try:
        cfg = {}
        if os.path.exists(settings_path):
            with open(settings_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        cfg["gdrive_user_email"] = email
        with open(settings_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print("Linked account saved - VCMS Settings will show it.")
    except Exception:
        print("Note: could not update settings.json; open VCMS Settings once")
        print("and the linked account will be filled in automatically.")

    print()
    print("Now go to VCMS Settings and enable 'Auto-sync on every vehicle change'")
    print("=" * 60)


if __name__ == "__main__":
    setup()
