"""Dashboard overview and fleet reports."""
from datetime import date, datetime, timedelta

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

REPORT_LABELS = {
    "puc_due": "PUC Due Report",
    "fitness_due": "Fitness Due Report",
    "tax_due": "Tax Due Report",
    "permit_due": "Permit Due Report",
    "insurance_due": "Insurance Due Report",
    "owner_wise": "Owner-wise Report",
    "type_wise": "Vehicle Type-wise Report",
    "monthly_renewals": "Monthly Renewals Report",
    "yearly_renewals": "Yearly Renewals Report",
}


@bp.route("/reports")
@login_required
def reports():
    report_type = request.args.get("type", "")
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in (7, 30, 90):
        days = 30

    vehicles = Vehicle.query.all()
    today = date.today()
    results = []
    summary = None

    due_field_map = {
        "puc_due": ("puc_expiry", "PUC"),
        "fitness_due": ("fitness_expiry", "Fitness"),
        "tax_due": ("tax_expiry", "Tax"),
        "permit_due": ("permit_expiry", "Permit"),
        "insurance_due": ("insurance_expiry", "Insurance"),
    }
    known_types = set(due_field_map) | {
        "owner_wise", "type_wise", "monthly_renewals", "yearly_renewals"}
    if report_type not in known_types:
        report_type = ""

    def expiry_info(expiry):
        label, css = Vehicle.status_for(expiry)
        return {"days": (expiry - today).days, "status": label, "class": css}

    # per-tab counts within the selected window (for tab badges)
    window_end = today + timedelta(days=days)
    due_counts = {
        key: sum(1 for v in vehicles
                 if getattr(v, field) and getattr(v, field) <= window_end)
        for key, (field, _label) in due_field_map.items()
    }

    if report_type in due_field_map:
        field, label = due_field_map[report_type]
        for v in vehicles:
            expiry = getattr(v, field)
            if expiry and expiry <= window_end:
                results.append({"vehicle": v, "field": label, "expiry": expiry,
                                **expiry_info(expiry)})
        results.sort(key=lambda r: r["expiry"])
        summary = {
            "expired": sum(1 for r in results if r["days"] < 0),
            "week": sum(1 for r in results if 0 <= r["days"] <= 7),
            "later": sum(1 for r in results if 7 < r["days"] <= days),
            "total": len(results),
            "days": days,
        }

    elif report_type == "owner_wise":
        grouped = {}
        for v in vehicles:
            grouped.setdefault(v.owner_name, []).append(v)
        results = sorted(grouped.items())
        summary = {"groups": len(results), "vehicles": len(vehicles)}

    elif report_type == "type_wise":
        grouped = {}
        for v in vehicles:
            grouped.setdefault(v.vehicle_type or "Unspecified", []).append(v)
        results = sorted(grouped.items())
        summary = {"groups": len(results), "vehicles": len(vehicles)}

    elif report_type == "monthly_renewals":
        grouped = {}
        for v in vehicles:
            for label, field in Vehicle.DOCUMENT_FIELDS.items():
                expiry = getattr(v, field)
                if expiry and expiry.year == today.year and expiry.month == today.month:
                    grouped.setdefault(f"{label}", []).append((v, expiry, expiry_info(expiry)))
        results = sorted(grouped.items())
        summary = {"groups": len(results),
                   "entries": sum(len(entries) for _g, entries in results)}

    elif report_type == "yearly_renewals":
        grouped = {}
        for v in vehicles:
            for label, field in Vehicle.DOCUMENT_FIELDS.items():
                expiry = getattr(v, field)
                if expiry and expiry.year == today.year:
                    grouped.setdefault(f"{label}", []).append((v, expiry, expiry_info(expiry)))
        results = sorted(grouped.items())
        summary = {"groups": len(results),
                   "entries": sum(len(entries) for _g, entries in results)}

    return render_template("reports.html", report_type=report_type, results=results,
                           summary=summary, days=days, due_counts=due_counts,
                           due_types=list(due_field_map),
                           report_label=REPORT_LABELS.get(report_type, ""),
                           generated=datetime.now().strftime("%d %b %Y, %I:%M %p"))


