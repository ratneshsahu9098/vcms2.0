"""Dashboard overview and fleet reports."""
from datetime import date, timedelta

from flask import (Blueprint, render_template, request)

from app.middleware import login_required
from app.models import (Vehicle)

bp = Blueprint("main", __name__)

# ---- Dashboard ---------------------------------------------------------

@bp.route("/")
@login_required
def dashboard():
    vehicles = Vehicle.query.all()
    today = date.today()

    total_vehicles = len(vehicles)
    expired_count = 0
    expiring_today = 0
    expiring_7 = 0
    expiring_30 = 0

    doc_card_stats = {label: {"valid": 0, "expiring": 0, "expired": 0} for label in Vehicle.DOCUMENT_FIELDS}

    for v in vehicles:
        statuses = v.document_statuses()
        worst = v.overall_status()
        if worst == "status-red":
            expired_count += 1
        elif worst == "status-orange":
            expiring_7 += 1
        elif worst == "status-yellow":
            expiring_30 += 1

        for label, info in statuses.items():
            if info["class"] == "status-red":
                doc_card_stats[label]["expired"] += 1
            elif info["class"] in ("status-orange", "status-yellow"):
                doc_card_stats[label]["expiring"] += 1
            elif info["class"] == "status-green":
                doc_card_stats[label]["valid"] += 1

        for label, info in statuses.items():
            if info["expiry"] == today:
                expiring_today += 1
                break

    recent_added = Vehicle.query.order_by(Vehicle.created_at.desc()).limit(5).all()
    recent_updated = Vehicle.query.order_by(Vehicle.updated_at.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        total_vehicles=total_vehicles,
        active_vehicles=total_vehicles - expired_count,
        expired_count=expired_count,
        expiring_today=expiring_today,
        expiring_7=expiring_7,
        expiring_30=expiring_30,
        doc_card_stats=doc_card_stats,
        recent_added=recent_added,
        recent_updated=recent_updated,
    )


# ---- Reports --------------------------------------------------------------

@bp.route("/reports")
@login_required
def reports():
    report_type = request.args.get("type", "")
    vehicles = Vehicle.query.all()
    today = date.today()
    results = []

    due_field_map = {
        "puc_due": ("puc_expiry", "PUC"),
        "fitness_due": ("fitness_expiry", "Fitness"),
        "tax_due": ("tax_expiry", "Tax"),
        "permit_due": ("permit_expiry", "Permit"),
        "insurance_due": ("insurance_expiry", "Insurance"),
    }

    if report_type in due_field_map:
        field, label = due_field_map[report_type]
        for v in vehicles:
            expiry = getattr(v, field)
            if expiry and expiry <= today + timedelta(days=30):
                results.append({"vehicle": v, "field": label, "expiry": expiry})
        results.sort(key=lambda r: r["expiry"])

    elif report_type == "owner_wise":
        grouped = {}
        for v in vehicles:
            grouped.setdefault(v.owner_name, []).append(v)
        results = sorted(grouped.items())

    elif report_type == "type_wise":
        grouped = {}
        for v in vehicles:
            grouped.setdefault(v.vehicle_type or "Unspecified", []).append(v)
        results = sorted(grouped.items())

    elif report_type == "monthly_renewals":
        grouped = {}
        for v in vehicles:
            for label, field in Vehicle.DOCUMENT_FIELDS.items():
                expiry = getattr(v, field)
                if expiry and expiry.year == today.year and expiry.month == today.month:
                    grouped.setdefault(f"{label}", []).append((v, expiry))
        results = sorted(grouped.items())

    elif report_type == "yearly_renewals":
        grouped = {}
        for v in vehicles:
            for label, field in Vehicle.DOCUMENT_FIELDS.items():
                expiry = getattr(v, field)
                if expiry and expiry.year == today.year:
                    grouped.setdefault(f"{label}", []).append((v, expiry))
        results = sorted(grouped.items())

    return render_template("reports.html", report_type=report_type, results=results)


