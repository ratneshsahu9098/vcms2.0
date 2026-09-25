"""Shared fixtures: isolated temp database, no scheduler, safe settings."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="vcms_pytest_")
os.environ["VCMS_DATABASE_URI"] = "sqlite:///" + os.path.join(_TMP, "test.db")
os.environ["VCMS_ADMIN_USER"] = "admin"
os.environ["VCMS_ADMIN_PASSWORD"] = "admin123"
os.environ["VCMS_LOGIN_REQUIRED"] = "true"

import pytest  # noqa: E402

import app.scheduler as _scheduler  # noqa: E402
_scheduler.start_scheduler = lambda application: None

import app.utils.settings as _settings  # noqa: E402
_settings.SETTINGS_FILE = os.path.join(_TMP, "settings.json")

from app import create_app  # noqa: E402


class CSRFClient:
    """test_client wrapper that carries the session CSRF token on every POST."""

    def __init__(self, client):
        self._client = client
        self._token = None

    def _remember(self, response):
        try:
            body = response.get_data(as_text=True)
        except UnicodeDecodeError:  # binary responses (QR PNGs, exports)
            return response
        match = re.search(r'name="csrf_token" value="([^"]+)"', body)
        if match:
            self._token = match.group(1)
        return response

    def get(self, *args, **kwargs):
        return self._remember(self._client.get(*args, **kwargs))

    def post(self, *args, **kwargs):
        if self._token is None:
            self._remember(self._client.get("/login"))
        data = dict(kwargs.pop("data", None) or {})
        data["csrf_token"] = self._token
        kwargs["data"] = data
        return self._remember(self._client.post(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._client, name)


@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return CSRFClient(app.test_client())


@pytest.fixture()
def auth_client(app):
    c = CSRFClient(app.test_client())
    c.post("/login", data={"username": "admin", "password": "admin123"})
    return c
