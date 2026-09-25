"""Vehicle CRUD and validation through the HTTP layer."""
from app.models import Vehicle, db

VALID = {
    "vehicle_number": "TST001",
    "chassis_number": "TSTCH001",
    "engine_number": "TSTEN001",
    "owner_name": "Test Owner",
    "mobile_number": "9876500999",
    "owner_email": "tstowner@example.com",
    "vehicle_type": "Truck",
    "district": "Indore",
    "permit_from": "2024-07-01",
    "permit_expiry": "2027-06-30",
    "permit_auth_no": "PER/777",
    "permit_address": "Nashik, MH",
}


def _cleanup(app, number):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number=number).delete()
        db.session.commit()


def test_add_edit_delete_vehicle(app, auth_client):
    _cleanup(app, "TST001")

    r = auth_client.post("/vehicles/add", data=VALID, follow_redirects=False)
    assert r.status_code == 302, "valid add should redirect"

    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TST001").first()
        assert v is not None
        assert v.owner_name == "Test Owner"
        assert str(v.permit_from) == "2024-07-01"
        assert v.permit_auth_no == "PER/777"
        assert v.permit_address == "Nashik, MH"
        vid = v.id

    # duplicate rejected (no redirect, form re-rendered with error)
    dup = dict(VALID, chassis_number="TSTCHDUP")
    r = auth_client.post("/vehicles/add", data=dup, follow_redirects=False)
    assert r.status_code == 200
    assert "already exists" in r.get_data(as_text=True)

    # edit
    edit = dict(VALID, vehicle_number="TST001", chassis_number="TSTCH001",
                owner_name="Renamed Owner")
    r = auth_client.post(f"/vehicles/{vid}/edit", data=edit, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        v = Vehicle.query.get(vid)
        assert v.owner_name == "Renamed Owner"

    # edit page structure: no nested <form> (delete must be a formaction button)
    from html.parser import HTMLParser

    class _FormDepth(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.max_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag == "form":
                self.depth += 1
                self.max_depth = max(self.max_depth, self.depth)

        def handle_endtag(self, tag):
            if tag == "form" and self.depth:
                self.depth -= 1

    r = auth_client.get(f"/vehicles/{vid}/edit")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'formaction="/vehicles/%d/delete"' % vid in html
    parser = _FormDepth()
    parser.feed(html)
    assert parser.max_depth <= 1, "edit page must not nest forms"

    # delete
    r = auth_client.post(f"/vehicles/{vid}/delete", follow_redirects=False)
    assert r.status_code in (302, 200)
    with app.app_context():
        assert Vehicle.query.get(vid) is None


def test_validation_errors(app, auth_client):
    r = auth_client.post("/vehicles/add", data={
        "vehicle_number": "", "chassis_number": "", "owner_name": "",
        "mobile_number": "abc",
    }, follow_redirects=False)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Vehicle Number is required." in html
    assert "Chassis Number is required." in html
    assert "Owner Name is required." in html
    assert "Mobile Number should be numeric." in html
