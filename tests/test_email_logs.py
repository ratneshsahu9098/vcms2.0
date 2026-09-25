"""Email logging: kinds (reminder/details/test), grouping, warnings, filters."""
from datetime import date, timedelta

import pytest

from app.models import ReminderLog, Vehicle, db
from app.services import email_service


def fake_ok(to_email, subject, html_body):
    return {"ok": True, "recipients": [to_email]}


def fake_warn(to_email, subject, html_body):
    return {"ok": True, "warning": "Delivered to a@x.com; failed for b@x.com"}


@pytest.fixture()
def mail(monkeypatch):
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(email_service, "send_email", fake_ok)
    return monkeypatch


@pytest.fixture()
def logged_in_vehicles(app, mail):
    today = date.today()
    with app.app_context():
        Vehicle.query.filter(Vehicle.vehicle_number.in_(["LOG01", "LOG02", "LOG03"])).delete()
        ReminderLog.query.filter(ReminderLog.recipient_email.in_([
            "logone@example.com", "logtwo@example.com", "qa@example.com",
            "legacy@old.com", "multi1@example.com", "multi2@example.com",
        ])).delete(synchronize_session=False)
        db.session.commit()

        v1 = Vehicle(vehicle_number="LOG01", chassis_number="LOGCH1",
                     owner_name="Log Owner One", mobile_number="9876500011",
                     owner_email="logone@example.com",
                     puc_expiry=today + timedelta(days=5))
        v2 = Vehicle(vehicle_number="LOG02", chassis_number="LOGCH2",
                     owner_name="Log Owner Two", mobile_number="9876500012",
                     owner_email="logtwo@example.com")
        v3 = Vehicle(vehicle_number="LOG03", chassis_number="LOGCH3",
                     owner_name="Log Owner One", mobile_number="9876500013",
                     owner_email="logone@example.com")
        v4 = Vehicle(vehicle_number="LOG04", chassis_number="LOGCH4",
                     owner_name="Multi Owner", mobile_number="9876500014",
                     owner_email="multi1@example.com, multi2@example.com")
        db.session.add_all([v1, v2, v3, v4])
        db.session.commit()
        ids = (v1.id, v2.id, v3.id, v4.id)

        # legacy row with kind NULL -> exercise backfill in run_migrations
        db.session.execute(db.text(
            "INSERT INTO reminder_logs (vehicle_id, document_type, recipient_email,"
            " status, sent_at, kind) VALUES (:v, 'PUC', 'legacy@old.com', 'sent',"
            " :t, NULL)"),
            {"v": ids[1], "t": today.isoformat() + " 09:00:00"})
        db.session.commit()

    from app.migrations import run_migrations
    with app.app_context():
        run_migrations()

    yield ids

    with app.app_context():
        ReminderLog.query.filter(
            ReminderLog.vehicle_id.in_(ids)
            | ReminderLog.recipient_email.in_([
                "logone@example.com", "logtwo@example.com", "qa@example.com",
                "legacy@old.com", "multi1@example.com", "multi2@example.com",
            ])
        ).delete(synchronize_session=False)
        Vehicle.query.filter(Vehicle.id.in_(ids)).delete()
        db.session.commit()


def test_email_log_kinds_and_grouping(app, auth_client, mail, logged_in_vehicles):
    id1, id2, id3, id4 = logged_in_vehicles

    r1 = auth_client.post(f"/vehicles/{id1}/email-all-details")
    assert r1.status_code == 302

    r2 = auth_client.post("/vehicles/email-vehicle-details",
                          data={"scope": "all", "vehicle_ids": f"{id1},{id2},{id3}"})
    assert r2.status_code == 302

    r3 = auth_client.post("/settings/test-email", data={"test_email_to": "qa@example.com"})
    assert r3.get_json().get("ok")

    r4 = auth_client.post(f"/vehicles/{id1}/email-reminder")
    assert r4.status_code == 302

    # warning path keeps the row but stores the warning
    mail.setattr(email_service, "send_email", fake_warn)
    r5 = auth_client.post(f"/vehicles/{id2}/email-all-details")
    assert r5.status_code == 302

    with app.app_context():
        def rows(**kw):
            return ReminderLog.query.filter_by(**kw).all()

        d1 = rows(kind="details", vehicle_id=id1, document_type="All Details")
        assert len(d1) == 1 and d1[0].status == "sent"
        assert d1[0].recipient_email == "logone@example.com"

        grp = rows(kind="details", document_type="Details (2 vehicles)")
        assert len(grp) == 1 and grp[0].vehicle_id is None
        assert grp[0].recipient_email == "logone@example.com"

        d2 = rows(kind="details", vehicle_id=id2, document_type="All Details")
        assert len(d2) == 2  # second send produced the warning row
        warn = [r for r in d2 if r.error_message]
        assert len(warn) == 1 and warn[0].status == "sent"
        assert "failed for b@x.com" in warn[0].error_message

        t = rows(kind="test", recipient_email="qa@example.com")
        assert len(t) == 1 and t[0].vehicle_id is None
        assert t[0].document_type == "Test Email"

        rem = rows(kind="reminder", vehicle_id=id1, document_type="PUC")
        assert len(rem) == 1 and rem[0].recipient_email == "logone@example.com"

        legacy = rows(recipient_email="legacy@old.com")
        assert len(legacy) == 1 and legacy[0].kind == "reminder"


def test_reminder_reports_smtp_failure(app, auth_client, mail, logged_in_vehicles):
    id1, *_ = logged_in_vehicles

    def fake_fail(to_email, subject, html_body):
        return {"ok": False, "error": "connection refused"}

    mail.setattr(email_service, "send_email", fake_fail)
    r = auth_client.post(f"/vehicles/{id1}/email-reminder", follow_redirects=True)
    assert "Failed to send email: connection refused" in r.get_data(as_text=True)

    with app.app_context():
        rows = ReminderLog.query.filter_by(kind="reminder", vehicle_id=id1).all()
        assert rows and all(x.status == "failed" for x in rows)


def test_multi_recipient_owner_email_logs_each_recipient(app, auth_client, mail,
                                                          logged_in_vehicles):
    _, _, _, id4 = logged_in_vehicles
    r = auth_client.post(f"/vehicles/{id4}/email-all-details")
    assert r.status_code == 302
    with app.app_context():
        recips = sorted(
            lr.recipient_email for lr in
            ReminderLog.query.filter_by(kind="details", vehicle_id=id4).all())
        assert recips == ["multi1@example.com", "multi2@example.com"]


def test_reminders_page_filters(app, auth_client, mail, logged_in_vehicles):
    id1, id2, id3, _ = logged_in_vehicles
    auth_client.post(f"/vehicles/{id1}/email-all-details")
    auth_client.post("/vehicles/email-vehicle-details",
                     data={"scope": "all", "vehicle_ids": f"{id1},{id2},{id3}"})
    auth_client.post("/settings/test-email", data={"test_email_to": "qa@example.com"})
    auth_client.post(f"/vehicles/{id1}/email-reminder")

    html = auth_client.get("/reminders").get_data(as_text=True)
    assert "Email Logs" in html
    assert "badge-blue" in html
    assert "Test Email" in html
    assert "Bulk / System" in html
    assert "legacy@old.com" in html

    hd = auth_client.get("/reminders?kind=details").get_data(as_text=True)
    assert "logone@example.com" in hd and "logtwo@example.com" in hd
    assert "qa@example.com" not in hd and "legacy@old.com" not in hd

    ht = auth_client.get("/reminders?kind=test").get_data(as_text=True)
    assert "qa@example.com" in ht and "legacy@old.com" not in ht

    hr = auth_client.get("/reminders?kind=reminder").get_data(as_text=True)
    assert "legacy@old.com" in hr and "PUC" in hr
    assert "Details (2 vehicles)" not in hr

    hk = auth_client.get("/reminders?kind=details&status=sent").get_data(as_text=True)
    assert "kind=details" in hk
