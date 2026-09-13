"""
Google Drive Setup Helper
Run this once to connect your Google account to VCMS.

Steps:
1. Create Google Cloud project (5 min): see instructions below
2. Download client_secret.json → place in project root
3. Run: python setup_gdrive.py
4. Browser opens → login with Google → done!
"""

import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CLIENT_SECRET = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


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
        print("9. Place it in:", BASE_DIR)
        print()
        print("Then run this script again: python setup_gdrive.py")
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
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print()
    print("=" * 60)
    print("SUCCESS! Google Drive is now connected.")
    print("Token saved to:", TOKEN_FILE)
    print()

    # Test connection
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds)
        about = service.about().get(fields="user(emailAddress)").execute()
        email = about.get("user", {}).get("emailAddress", "unknown")
        print(f"Connected as: {email}")
    except Exception:
        print("Connection verified.")

    print()
    print("Now go to VCMS Settings and enable 'Auto-sync on every vehicle change'")
    print("=" * 60)


if __name__ == "__main__":
    setup()
