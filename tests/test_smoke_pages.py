"""Render sweep: every GET page must build URLs and render without errors.

A missed blueprint endpoint rename shows up here as a BuildError/500.
"""
from datetime import date, timedelta

import pytest

from app.models import Vehicle, db

EXCLUDE_ENDPOINTS = {
    "static",
    "auth.logout",
    "backup.gdrive_connect",
    "backup.gdrive_callback",
    "data.export_run",
}


@pytest.fixture()
def seeded_vehicle(app):
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="SMOKE01").first()
        if v is None:
            v = Vehicle(
                vehicle_number="SMOKE01",
                chassis_number="SMOKECH1",
                owner_name="Smoke Owner",
                mobile_number="9876500001",
                owner_email="smoke1@example.com, smoke2@example.com",
                puc_expiry=date.today() + timedelta(days=10),
            )
            db.session.add(v)
            db.session.commit()
        vid = v.id
    yield vid
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="SMOKE01").delete()
        db.session.commit()


def test_login_required_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "password" in r.get_data(as_text=True).lower()


def test_all_get_pages_render(auth_client, app, seeded_vehicle):
    urls = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in EXCLUDE_ENDPOINTS or "GET" not in rule.methods:
            continue
        if "<" in rule.rule:
            continue
        urls.append(rule.rule)
    assert urls, "no GET routes discovered"

    failures = []
    for url in sorted(urls):
        try:
            resp = auth_client.get(url)
            if resp.status_code >= 500:
                failures.append((url, f"HTTP {resp.status_code}"))
        except Exception as exc:  # noqa: BLE001 - collect all build errors
            failures.append((url, repr(exc)))
    assert not failures, f"pages failed: {failures}"


def test_vehicle_detail_pages_render(auth_client, seeded_vehicle):
    vid = seeded_vehicle
    urls = [
        f"/vehicles/{vid}",
        f"/vehicles/{vid}/edit",
        f"/vehicles/{vid}/print",
        f"/vehicles/{vid}/qr",
        f"/vehicles/{vid}/qr-dates",
        f"/vehicles/{vid}/tax",
        f"/vehicles/{vid}/tax/add",
        f"/vehicles/{vid}/whatsapp-expired",
        f"/vehicles/{vid}/whatsapp/PUC",
        f"/api/vehicle/{vid}",
        "/vehicles/print",
        "/vehicles/print-qr",
    ]
    failures = []
    for url in urls:
        try:
            resp = auth_client.get(url)
            if resp.status_code >= 500:
                failures.append((url, resp.status_code))
        except Exception as exc:  # noqa: BLE001
            failures.append((url, repr(exc)))
    assert not failures, f"detail pages failed: {failures}"


def test_duplicate_check_api(auth_client, seeded_vehicle):
    j = auth_client.get("/api/check-duplicate?field=vehicle_number&value=SMOKE01").get_json()
    assert j["exists"] is True
    j = auth_client.get("/api/check-duplicate?field=vehicle_number&value=NOPE99").get_json()
    assert j["exists"] is False
