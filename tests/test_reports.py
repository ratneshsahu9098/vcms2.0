"""Reports page: due window selector, status badges, summaries, grouping."""
from datetime import date, timedelta

from app.models import Vehicle, db


def _make(app, number, **kw):
    with app.app_context():
        Vehicle.query.filter_by(vehicle_number=number).delete()
        db.session.commit()
        v = Vehicle(vehicle_number=number, chassis_number=number + "CH",
                    owner_name="Report Owner", mobile_number="9876500101", **kw)
        db.session.add(v)
        db.session.commit()


def _drop(app, *numbers):
    with app.app_context():
        Vehicle.query.filter(Vehicle.vehicle_number.in_(numbers)).delete()
        db.session.commit()


def test_reports_default_and_invalid_params(app, auth_client):
    r = auth_client.get("/reports")
    assert r.status_code == 200
    assert "Select a report type" in r.get_data(as_text=True)

    # unknown report type falls back to the empty state
    r = auth_client.get("/reports?type=bogus")
    assert r.status_code == 200
    assert "Select a report type" in r.get_data(as_text=True)

    # invalid window falls back to 30 days
    for bad in ("abc", "999"):
        html = auth_client.get(f"/reports?type=puc_due&days={bad}").get_data(as_text=True)
        assert 'window-chip active">30 days' in html


def test_due_report_window_filtering_and_badges(app, auth_client):
    today = date.today()
    expired, soon, later = "RPTX1", "RPTS1", "RPTL1"
    _make(app, expired, puc_expiry=today - timedelta(days=3))
    _make(app, soon, puc_expiry=today + timedelta(days=5))
    _make(app, later, puc_expiry=today + timedelta(days=45))
    try:
        html = auth_client.get("/reports?type=puc_due&days=30").get_data(as_text=True)
        assert expired in html and soon in html
        assert later not in html, "45-day expiry must be outside the 30-day window"
        assert "badge-status status-red" in html
        assert "3 days overdue" in html
        assert "5 days" in html
        assert "window.print()" in html, "print button present"
        assert "report-summary" in html
        assert "print-header" in html and "PUC Due Report" in html
        assert "Window: next 30 days" in html

        html = auth_client.get("/reports?type=puc_due&days=90").get_data(as_text=True)
        assert later in html, "90-day window includes the 45-day expiry"
        assert 'window-chip active">90 days' in html

        html = auth_client.get("/reports?type=puc_due&days=7").get_data(as_text=True)
        assert expired in html and soon in html and later not in html
        assert 'window-chip active">7 days' in html
    finally:
        _drop(app, expired, soon, later)


def test_grouped_reports_render(app, auth_client):
    _make(app, "RPTG1", vehicle_type="Truck")
    try:
        for t in ("owner_wise", "type_wise", "monthly_renewals", "yearly_renewals"):
            r = auth_client.get(f"/reports?type={t}")
            assert r.status_code == 200, t
            assert "report-summary" in r.get_data(as_text=True), t

        html = auth_client.get("/reports?type=owner_wise").get_data(as_text=True)
        assert "RPTG1" in html
        assert "badge-status" in html, "status column on grouped rows"

        html = auth_client.get("/reports?type=type_wise").get_data(as_text=True)
        assert "Truck" in html and "badge-status" in html
    finally:
        _drop(app, "RPTG1")
