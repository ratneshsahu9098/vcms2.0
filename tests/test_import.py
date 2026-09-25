"""Import wizard: sample template, preview, commit, duplicates, cancel."""
import io
import json
import os
import re

from app.config import Config
from app.models import Vehicle, db

CSV_ONE = (
    "Vehicle Number,Chassis Number,Owner Name,Phone,Owner Email,PUC Expiry\n"
    "IMP001,IMPCH001,Import Owner,9876500111,imp1@example.com,2026-12-31\n"
)
CSV_MISSING_CHASSIS = (
    "Vehicle Number,Chassis Number,Owner Name,Phone\n"
    "IMP002,,No Chassis Here,9876500222\n"
)
CSV_NO_OWNER = "Vehicle Number,Chassis Number,Phone\nIMP003,IMPCH003,9876500333\n"


def _cleanup(app, number):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number=number).delete()
        db.session.commit()


def _file(body, name="imp.csv"):
    return {"file": (io.BytesIO(body.encode("utf-8")), name)}


def _token(html):
    match = re.search(r'name="token" value="([^"]+)"', html)
    return match.group(1) if match else None


def test_sample_template(auth_client):
    r = auth_client.get("/import?download=template")
    assert r.status_code == 200
    assert "csv" in r.headers.get("Content-Type", "")
    body = r.get_data(as_text=True)
    for col in ("Vehicle Number", "Chassis Number", "Owner Name", "Phone", "PUC Expiry"):
        assert col in body
    assert "vehicle_import_template.csv" in r.headers.get("Content-Disposition", "")


def test_preview_then_commit(app, auth_client):
    _cleanup(app, "IMP001")
    r = auth_client.post(
        "/import",
        data=dict(_file(CSV_ONE), phase="preview", duplicate_action="skip"),
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    token = _token(html)
    assert token, "preview renders a commit token"
    assert "Nothing has been saved yet" in html
    assert "Column mapping" in html
    assert "act-add" in html

    # preview must not write to the database
    with app.app_context():
        assert Vehicle.query.filter_by(vehicle_number="IMP001").first() is None

    r = auth_client.post("/import", data={"phase": "commit", "token": token},
                         follow_redirects=False)
    assert r.status_code == 302
    html = auth_client.get("/import").get_data(as_text=True)
    assert "Import complete" in html
    assert "1 added, 0 updated, 0 skipped" in html
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="IMP001").first()
        assert v is not None
        assert v.owner_name == "Import Owner"
        assert str(v.puc_expiry) == "2026-12-31"
    _cleanup(app, "IMP001")


def test_missing_required_column(app, auth_client):
    with app.app_context():
        before = Vehicle.query.count()
    r = auth_client.post(
        "/import",
        data=dict(_file(CSV_NO_OWNER), phase="preview"),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    html = r.get_data(as_text=True)
    assert "Missing required columns: owner_name" in html
    with app.app_context():
        assert Vehicle.query.count() == before


def test_error_row_preview_and_commit(app, auth_client):
    _cleanup(app, "IMP002")
    r = auth_client.post(
        "/import",
        data=dict(_file(CSV_MISSING_CHASSIS), phase="preview"),
        content_type="multipart/form-data",
    )
    html = r.get_data(as_text=True)
    token = _token(html)
    assert "act-error" in html
    assert "Missing vehicle or chassis number" in html

    r = auth_client.post("/import", data={"phase": "commit", "token": token},
                         follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Import complete" in html
    assert "0 added" in html
    assert "Rows skipped" in html
    with app.app_context():
        assert Vehicle.query.filter_by(vehicle_number="IMP002").first() is None
    _cleanup(app, "IMP002")


def test_duplicate_skip_and_update(app, auth_client):
    _cleanup(app, "IMP001")
    with app.app_context():
        db.session.add(Vehicle(vehicle_number="IMP001", chassis_number="IMPCH001",
                               owner_name="Old Owner", mobile_number="9876500111"))
        db.session.commit()

    try:
        # skip: preview shows it, commit leaves data untouched
        r = auth_client.post(
            "/import",
            data=dict(_file(CSV_ONE), phase="preview", duplicate_action="skip"),
            content_type="multipart/form-data",
        )
        html = r.get_data(as_text=True)
        assert "act-skip" in html and "Duplicate of IMP001" in html
        token = _token(html)
        auth_client.post("/import", data={"phase": "commit", "token": token})
        with app.app_context():
            v = Vehicle.query.filter_by(vehicle_number="IMP001").first()
            assert v.owner_name == "Old Owner"

        # update: preview shows update, commit overwrites owner
        r = auth_client.post(
            "/import",
            data=dict(_file(CSV_ONE), phase="preview", duplicate_action="update"),
            content_type="multipart/form-data",
        )
        html = r.get_data(as_text=True)
        assert "act-update" in html
        token = _token(html)
        auth_client.post("/import", data={"phase": "commit", "token": token},
                         follow_redirects=True)
        with app.app_context():
            v = Vehicle.query.filter_by(vehicle_number="IMP001").first()
            assert v.owner_name == "Import Owner"
    finally:
        _cleanup(app, "IMP001")


def test_json_import(app, auth_client):
    _cleanup(app, "IMPJ01")
    payload = json.dumps([{
        "vehicle_number": "IMPJ01", "chassis_number": "IMPJCH01",
        "owner_name": "JSON Owner", "mobile_number": "9876500444",
        "puc_expiry": "2026-11-11",
    }])
    r = auth_client.post(
        "/import",
        data=dict(_file(payload, name="imp.json"), phase="preview"),
        content_type="multipart/form-data",
    )
    html = r.get_data(as_text=True)
    token = _token(html)
    assert token
    auth_client.post("/import", data={"phase": "commit", "token": token})
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="IMPJ01").first()
        assert v is not None
        assert str(v.puc_expiry) == "2026-11-11"
    _cleanup(app, "IMPJ01")

    # non-array JSON is rejected
    r = auth_client.post(
        "/import",
        data=dict(_file('{"vehicle_number": "X"}', name="bad.json"), phase="preview"),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "non-empty array" in r.get_data(as_text=True)


def test_cancel_and_expired_token(app, auth_client):
    _cleanup(app, "IMPC01")
    r = auth_client.post(
        "/import",
        data=dict(_file(CSV_ONE, name="c.csv").copy(), phase="preview"),
        content_type="multipart/form-data",
    )
    html = r.get_data(as_text=True)
    token = _token(html)
    assert token
    cache_file = os.path.join(Config.IMPORT_CACHE_DIR, token + ".json")
    assert os.path.isfile(cache_file)

    # cancel purges the cache; committing afterwards fails safely
    auth_client.get(f"/import?cancel={token}")
    assert not os.path.isfile(cache_file)
    r = auth_client.post("/import", data={"phase": "commit", "token": token},
                         follow_redirects=True)
    assert "Import session expired" in r.get_data(as_text=True)

    # unknown token is rejected the same way
    r = auth_client.post("/import", data={"phase": "commit", "token": "x" * 32},
                         follow_redirects=True)
    assert "Import session expired" in r.get_data(as_text=True)
    with app.app_context():
        assert Vehicle.query.filter_by(vehicle_number="IMP001").first() is None
    _cleanup(app, "IMP001")
    _cleanup(app, "IMPC01")
