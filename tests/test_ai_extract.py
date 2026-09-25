"""AI document parsing: prompt, tax+permit extraction, form save, template."""
import json
from types import SimpleNamespace

import pytest

from app.models import Vehicle, db
from app.services import ai_service

TAX_JSON = json.dumps({
    "vehicle_number": "MH12AB1234", "chassis_number": "CH123", "engine_number": "EN123",
    "owner_name": "Ravi Kumar", "registration_date": "2021-06-15",
    "puc_expiry": None, "fitness_expiry": None,
    "permit_from": "2024-04-01", "permit_expiry": "2027-03-31",
    "permit_auth_no": "AP/2024/11235", "permit_address": "Pune, MH",
    "insurance_expiry": None, "insurance_company": None, "policy_number": None,
    "vehicle_type": "Truck",
    "tax_from": "2025-04-01", "tax_expiry": "2025-06-30",
    "tax_mode": "Quarterly (Q)", "tax_amount": 5400,
    "document_type": "Tax Receipt",
})


@pytest.fixture()
def parsed_tax(monkeypatch):
    monkeypatch.setattr(
        ai_service, "chat_completion",
        lambda messages: "```json\n" + TAX_JSON + "\n```")
    return ai_service.parse_document_text("tax receipt ocr text")


def test_prompt_asks_for_tax_and_permit():
    prompt = ai_service.PARSE_PROMPT.format(ocr_text="SAMPLE OCR")
    assert "tax_expiry" in prompt
    assert all(k in prompt for k in ("tax_from", "tax_amount", "tax_mode"))
    assert "Tax Receipt" in prompt
    assert all(k in prompt for k in
               ('"permit_from"', '"permit_expiry"', '"permit_auth_no"', '"permit_address"'))
    assert "permit_auth_no is the permit/authorisation number" in prompt


def test_parse_document_text_extracts_tax_and_permit(parsed_tax):
    assert parsed_tax.get("tax_from") == "2025-04-01"
    assert parsed_tax.get("tax_expiry") == "2025-06-30"
    assert parsed_tax.get("tax_mode") == "Quarterly (Q)"
    assert parsed_tax.get("tax_amount") == 5400
    assert parsed_tax.get("permit_from") == "2024-04-01"
    assert parsed_tax.get("permit_expiry") == "2027-03-31"
    assert parsed_tax.get("permit_auth_no") == "AP/2024/11235"
    assert parsed_tax.get("permit_address") == "Pune, MH"
    assert parsed_tax.get("document_type") == "Tax Receipt"


def test_parser_template_form_mode(app, parsed_tax):
    with app.test_request_context("/ai/parse-document"):
        from flask import session
        session["logged_in"] = True  # layout hides content until logged in
        html = app.jinja_env.get_template("ai_document_parser.html").render(
            parsed_data=parsed_tax, ocr_text="ocr text", ai_enabled=True,
            last_scans=[], current_scan_id=7, existing_vehicle=None, comparison=None,
        )
        assert all(s in html for s in
                   ("Tax Valid Until", "Tax Mode", "Tax Amount", "5400"))
        assert all(s in html for s in
                   ("Permit From", "Permit Auth No.", "AP/2024/11235", "Pune, MH"))
        assert all(s in html for s in
                   ('name="tax_from"', 'name="tax_expiry"', 'name="tax_mode"',
                    'name="tax_amount"'))
        assert all(s in html for s in
                   ('name="permit_from"', 'name="permit_auth_no"',
                    'name="permit_address"'))
        assert 'value="2024-04-01"' in html
        assert 'value="AP/2024/11235"' in html
        assert "Quarterly (Q)" in html
        assert 'name="scan_id" value="7"' in html
        assert "ocr text" in html  # raw OCR panel
        assert 'action="/ai/parse-document/add"' in html
        assert "Add Vehicle" in html


def test_parser_template_requires_api_key(app):
    with app.test_request_context("/ai/parse-document"):
        from flask import session
        session["logged_in"] = True
        html = app.jinja_env.get_template("ai_document_parser.html").render(
            parsed_data=None, ocr_text=None, ai_enabled=False, last_scans=[])
        assert "API Key Not Configured" in html


def test_parser_template_comparison_panel(app, parsed_tax):
    from app.services.document_service import build_comparison
    existing = SimpleNamespace(
        id=5, vehicle_number="MH12AB1234", chassis_number="CH123",
        engine_number="EN123", owner_name="Old Name")
    rows = build_comparison(existing, parsed_tax)
    statuses = {r["field"]: r["status"] for r in rows}
    assert statuses["engine_number"] == "same"
    assert statuses["owner_name"] == "changed"
    assert statuses["registration_date"] == "empty"
    assert statuses["tax_amount"] == "empty"

    with app.test_request_context("/ai/parse-document"):
        from flask import session
        session["logged_in"] = True
        html = app.jinja_env.get_template("ai_document_parser.html").render(
            parsed_data=parsed_tax, ocr_text="ocr", ai_enabled=True,
            last_scans=[], current_scan_id=7, existing_vehicle=existing,
            comparison=rows)
        assert "Field Comparison" in html
        assert all(s in html for s in ("Auto-fill", "Changed", "Same"))
        assert 'name="accepted_fields"' in html
        assert 'value="owner_name"' in html
        assert "View existing record" in html
        assert "Apply Updates" in html


def test_parse_add_route_saves_new_vehicle_tax_permit(app, auth_client):
    with app.app_context():
        Vehicle.query.filter(
            Vehicle.vehicle_number.in_(["TAXAI01", "TAXAI02", "TAXAI03"])).delete()
        db.session.commit()

    r = auth_client.post("/ai/parse-document/add", data={
        "vehicle_number": "TAXAI01", "chassis_number": "TAXCH1",
        "owner_name": "Tax Owner", "vehicle_type": "Truck",
        "tax_from": "2025-04-01", "tax_expiry": "2025-06-30",
        "tax_mode": "Quarterly (Q)", "tax_amount": "5400",
        "permit_from": "2024-04-01", "permit_expiry": "2027-03-31",
        "permit_auth_no": "AP/2024/11235", "permit_address": "Pune, MH",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TAXAI01").first()
        assert v is not None
        assert str(v.tax_from) == "2025-04-01"
        assert str(v.tax_expiry) == "2025-06-30"
        assert v.tax_mode == "Quarterly (Q)"
        assert float(v.tax_amount) == 5400.0
        assert str(v.permit_from) == "2024-04-01"
        assert str(v.permit_expiry) == "2027-03-31"
        assert v.permit_auth_no == "AP/2024/11235"
        assert v.permit_address == "Pune, MH"

    with app.app_context():
        Vehicle.query.filter(
            Vehicle.vehicle_number.in_(["TAXAI01", "TAXAI02", "TAXAI03"])).delete()
        db.session.commit()


def test_parse_add_updates_existing_comparison_apply(app, auth_client):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="TAXAI04").delete()
        db.session.commit()
        db.session.add(Vehicle(vehicle_number="TAXAI04", chassis_number="TAXCH4",
                               owner_name="Old Owner", mobile_number="9800000004"))
        db.session.commit()

    r = auth_client.post("/ai/parse-document/add", data={
        "vehicle_number": "TAXAI04", "chassis_number": "TAXCH4",
        "owner_name": "New Owner",
        "tax_from": "2025-04-01", "tax_expiry": "2025-06-30",
        "tax_mode": "Quarterly (Q)", "tax_amount": "5400",
        "permit_auth_no": "PER/900",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TAXAI04").first()
        assert str(v.tax_from) == "2025-04-01"
        assert str(v.tax_expiry) == "2025-06-30"
        assert v.permit_auth_no == "PER/900"
        assert v.owner_name == "Old Owner"  # changed, not accepted -> untouched

    auth_client.post("/ai/parse-document/add", data={
        "vehicle_number": "TAXAI04", "chassis_number": "TAXCH4",
        "owner_name": "New Owner", "accepted_fields": "owner_name",
    }, follow_redirects=True)
    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TAXAI04").first()
        assert v.owner_name == "New Owner"
        assert str(v.tax_expiry) == "2025-06-30"  # unchanged by second submit
        Vehicle.query.filter_by(vehicle_number="TAXAI04").delete()
        db.session.commit()


def test_parse_document_upload_flow_shows_comparison(app, auth_client, monkeypatch):
    import io
    from PIL import Image

    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="UPLOADAI1").delete()
        db.session.commit()
        db.session.add(Vehicle(vehicle_number="UPLOADAI1", chassis_number="UPCH1",
                               owner_name="Old Owner", mobile_number="9800000001"))
        db.session.commit()

    monkeypatch.setattr(ai_service, "check_api_key", lambda: True)
    monkeypatch.setattr("pytesseract.image_to_string", lambda img: "OCR TEXT")
    monkeypatch.setattr(ai_service, "parse_document_text", lambda ocr: {
        "vehicle_number": "UPLOADAI1", "chassis_number": "UPCH1",
        "owner_name": "Fresh Owner", "tax_from": "2025-04-01",
        "tax_expiry": "2025-06-30", "tax_mode": "Quarterly (Q)",
        "tax_amount": 5400, "permit_auth_no": "UP/1",
        "document_type": "Tax Receipt",
    })

    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buf, "PNG")
    buf.seek(0)
    r = auth_client.post(
        "/ai/parse-document",
        data={"document": (buf, "rc.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Document Scanned Successfully" in body
    assert "Field Comparison" in body
    assert 'name="accepted_fields" value="owner_name"' in body  # changed
    assert "Auto-fill" in body  # tax/permit fields empty in DB
    assert 'name="scan_id" value="' in body

    with app.app_context():
        from app.models import DocumentScan
        scan = DocumentScan.query.order_by(DocumentScan.id.desc()).first()
        assert scan is not None and scan.file_name == "rc.png"
        db.session.delete(scan)
        Vehicle.query.filter_by(vehicle_number="UPLOADAI1").delete()
        db.session.commit()


def test_add_form_saves_permit_fields(app, auth_client):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="TAXAI03").delete()
        db.session.commit()

    r = auth_client.post("/vehicles/add", data={
        "vehicle_number": "TAXAI03", "chassis_number": "TAXCH3",
        "owner_name": "Form Owner", "mobile_number": "9876500003",
        "permit_from": "2024-07-01", "permit_expiry": "2027-06-30",
        "permit_auth_no": "PER/777", "permit_address": "Nashik, MH",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        v = Vehicle.query.filter_by(vehicle_number="TAXAI03").first()
        assert v is not None
        assert str(v.permit_from) == "2024-07-01"
        assert v.permit_auth_no == "PER/777"
        assert v.permit_address == "Nashik, MH"
        vid = v.id

    html = auth_client.get(f"/vehicles/{vid}").get_data(as_text=True)
    assert all(s in html for s in ("Permit Auth No.", "PER/777", "Nashik, MH"))

    with app.app_context():
        Vehicle.query.filter_by(vehicle_number="TAXAI03").delete()
        db.session.commit()


def test_migrations_added_permit_columns(app):
    with app.app_context():
        cols = [c["name"] for c in db.inspect(db.engine).get_columns("vehicles")]
    assert all(c in cols for c in ("permit_from", "permit_auth_no", "permit_address"))


def test_parse_document_page_get(app, auth_client):
    assert auth_client.get("/ai/parse-document").status_code == 200
