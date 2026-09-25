"""Input/path guard regressions: backup traversal, api allowlist, to_float."""
from app.models import TaxDetail, Vehicle, db
from app.utils import to_float


def test_to_float_handles_junk():
    assert to_float("1,234.5") == 1234.5
    assert to_float(" 5400 ") == 5400.0
    assert to_float("abc") == 0.0
    assert to_float("") == 0.0
    assert to_float(None) == 0.0
    assert to_float("nan") == 0.0
    assert to_float(float("nan")) == 0.0
    assert to_float(12) == 12.0
    assert to_float("x", default=-1.0) == -1.0


def test_backup_download_rejects_traversal(app, auth_client):
    assert auth_client.get("/backup/download/..").status_code == 404
    assert auth_client.get("/backup/download/..\\..\\vehicles.db").status_code == 404
    assert auth_client.get("/backup/download/..%5C..%5Csettings.json").status_code == 404


def test_backup_restore_rejects_bad_name(app, auth_client):
    r = auth_client.post("/backup", data={"action": "restore", "backup_name": ".."},
                         follow_redirects=True)
    assert r.status_code == 200
    assert "Backup file not found." in r.get_data(as_text=True)


def test_check_duplicate_rejects_unknown_field(app, auth_client):
    r = auth_client.get("/api/check-duplicate?field=__class__&value=x")
    assert r.status_code == 400
    r = auth_client.get("/api/check-duplicate?field=vehicle_number&value=ZZZNONE")
    assert r.status_code == 200
    assert r.get_json() == {"exists": False}


def test_vehicle_add_with_junk_tax_amount(app, auth_client):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="TSTFLOAT1").delete()
        db.session.commit()

    r = auth_client.post("/vehicles/add", data={
        "vehicle_number": "TSTFLOAT1", "chassis_number": "TSTFLOATCH1",
        "owner_name": "Float Owner", "mobile_number": "9876501111",
        "tax_amount": "not-a-number",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TSTFLOAT1").first()
        assert v is not None
        assert float(v.tax_amount or 0) == 0.0
        Vehicle.query.filter_by(vehicle_number="TSTFLOAT1").delete()
        db.session.commit()


def test_tax_add_with_junk_amounts(app, auth_client):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="TSTTAXG1").delete()
        db.session.commit()

    auth_client.post("/vehicles/add", data={
        "vehicle_number": "TSTTAXG1", "chassis_number": "TSTTAXGCH1",
        "owner_name": "Tax Guard", "mobile_number": "9876502222",
    }, follow_redirects=False)
    with app.app_context():
        vid = Vehicle.query.filter_by(vehicle_number="TSTTAXG1").first().id

    r = auth_client.post(f"/vehicles/{vid}/tax/add", data={
        "tax_mode": "Quarterly (Q)", "tax_amount": "abc", "penalty": "x",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        t = TaxDetail.query.filter_by(vehicle_id=vid).first()
        assert t is not None
        assert float(t.tax_amount or 0) == 0.0
        assert float(t.penalty or 0) == 0.0
        Vehicle.query.filter_by(vehicle_number="TSTTAXG1").delete()
        db.session.commit()
