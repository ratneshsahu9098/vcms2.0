"""Vehicle CRUD and validation through the HTTP layer."""
from datetime import date, timedelta

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
    "pollution_certificate_number": "PUC-TEST-777",
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
        assert v.pollution_certificate_number == "PUC-TEST-777"
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
    assert r.headers.get("Location", "").endswith(f"/vehicles/{vid}"), \
        "save redirects to the vehicle view page"
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

    # PUC certificate number: saved value shows on the view page
    r = auth_client.get(f"/vehicles/{vid}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "PUC-TEST-777" in html

    # delete
    r = auth_client.post(f"/vehicles/{vid}/delete", follow_redirects=False)
    assert r.status_code in (302, 200)
    with app.app_context():
        assert Vehicle.query.get(vid) is None


def test_edit_page_upgrade(app, auth_client):
    _cleanup(app, "TSTUP1")
    with app.app_context():
        v = Vehicle(vehicle_number="TSTUP1", chassis_number="TSTUPCH1",
                    owner_name="Upgrade Owner", mobile_number="9876500777",
                    puc_expiry=date.today() + timedelta(days=5))
        db.session.add(v)
        db.session.commit()
        vid = v.id

    try:
        html = auth_client.get(f"/vehicles/{vid}/edit").get_data(as_text=True)
        assert "edit-header" in html, "header card present"
        assert f'href="/vehicles/{vid}"' in html, "back-to-vehicle link"
        assert "form-actions-sticky" in html, "sticky save bar"
        assert "expiry-badge" in html, "status badges on expiry fields"
        assert "status-orange" in html, "+5 day PUC renders orange badge"
        assert "beforeunload" in html, "unsaved-changes warning"
        assert 'data-section="documents"' in html, "collapsible sections"
        assert "section-count" in html, "fill counters"
        assert "field-changed" in html, "changed-field highlighting"

        # validation error re-render still shows badges (expiry_status from form)
        r = auth_client.post(f"/vehicles/{vid}/edit", data={
            "vehicle_number": "TSTUP1", "chassis_number": "TSTUPCH1",
            "owner_name": "X", "mobile_number": "abc",
        }, follow_redirects=False)
        assert r.status_code == 200
        assert "expiry-badge" in r.get_data(as_text=True)
    finally:
        _cleanup(app, "TSTUP1")


def test_mobile_email_filters(app, auth_client):
    for n in ("TSTF01", "TSTF02"):
        _cleanup(app, n)
    with app.app_context():
        db.session.add_all([
            Vehicle(vehicle_number="TSTF01", chassis_number="TSTFCH1",
                    owner_name="Filter One", mobile_number="9000011111",
                    owner_email="one@example.com, one.alt@example.com"),
            Vehicle(vehicle_number="TSTF02", chassis_number="TSTFCH2",
                    owner_name="Filter Two", mobile_number="9000022222",
                    owner_email="two@example.com"),
        ])
        db.session.commit()

    def page(url):
        html = auth_client.get(url).get_data(as_text=True)
        return "TSTF01" in html, "TSTF02" in html

    try:
        # exact mobile
        assert page("/vehicles?mobile=9000011111") == (True, False)
        # partial mobile
        assert page("/vehicles?mobile=222") == (False, True)
        # email inside a comma-separated list
        assert page("/vehicles?email=one.alt@example.com") == (True, False)
        # partial email
        assert page("/vehicles?email=two@") == (False, True)
        # global search also matches owner email now
        assert page("/vehicles?q=one.alt") == (True, False)
        # both filters combined
        assert page("/vehicles?mobile=9000&email=two@") == (False, True)
        # empty filters show everything
        assert page("/vehicles") == (True, True)
        # filter inputs present in the bar
        html = auth_client.get("/vehicles").get_data(as_text=True)
        assert 'name="mobile"' in html and 'name="email"' in html
    finally:
        for n in ("TSTF01", "TSTF02"):
            _cleanup(app, n)


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
