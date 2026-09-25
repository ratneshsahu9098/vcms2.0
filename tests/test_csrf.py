"""CSRF protection: POSTs without a valid session token are rejected."""


def test_login_page_carries_token(app):
    r = app.test_client().get("/login")
    assert r.status_code == 200
    assert b'name="csrf_token"' in r.data


def test_login_post_without_token_rejected(app):
    c = app.test_client()
    r = c.post("/login", data={"username": "admin", "password": "admin123"},
               follow_redirects=False)
    assert r.status_code == 400


def test_post_without_token_rejected(app):
    c = app.test_client()
    r = c.post("/vehicles/add", data={
        "vehicle_number": "CSRF1", "chassis_number": "CSRFC1",
        "owner_name": "X", "mobile_number": "9876500000",
    }, follow_redirects=False)
    assert r.status_code == 400


def test_post_with_wrong_token_rejected(app):
    c = app.test_client()
    c.get("/login")  # seeds a real session token
    r = c.post("/vehicles/add", data={"csrf_token": "not-the-real-token"},
               follow_redirects=False)
    assert r.status_code == 400


def test_post_with_token_accepted(app, auth_client):
    from app.models import Vehicle, db
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="CSRFT1").delete()
        db.session.commit()

    r = auth_client.post("/vehicles/add", data={
        "vehicle_number": "CSRFT1", "chassis_number": "CSRFTCH1",
        "owner_name": "CSRF Owner", "mobile_number": "9876500001",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="CSRFT1").first()
        assert v is not None
        Vehicle.query.filter_by(vehicle_number="CSRFT1").delete()
        db.session.commit()


def test_csrf_can_be_disabled_via_config(app, auth_client):
    app.config["CSRF_ENABLED"] = False
    try:
        r = auth_client.post("/vehicles/add", data={
            "vehicle_number": "", "chassis_number": "", "owner_name": "",
        }, follow_redirects=False)
        assert r.status_code == 200  # validation re-render, not 400
    finally:
        app.config["CSRF_ENABLED"] = True
