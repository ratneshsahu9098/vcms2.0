"""Manual email sends: reminders, full details reports, bulk sends."""
from datetime import date

from flask import (Blueprint, flash, redirect, request, url_for)

from app.middleware import login_required
from app.models import (Vehicle)
from app.services import email_service

bp = Blueprint("email", __name__)

# ---- Email reminders (SMTP) ----------------------------------------------

@bp.route("/vehicles/<int:vehicle_id>/email-reminder", methods=["POST"])
@login_required
def email_reminder(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    force = request.form.get("force") == "1"
    result = email_service.send_reminder(vehicle, force=force)
    if result.get("error"):
        flash(f"Failed to send email: {result['error']}", "error")
    elif result.get("sent"):
        flash(f"Email reminder sent to {vehicle.owner_email} for: {', '.join(result['sent'])}", "success")
    else:
        flash("No documents expiring within 30 days (or already reminded today). Nothing to send.", "info")
    return redirect(request.referrer or url_for("vehicles.view_vehicle", vehicle_id=vehicle.id))

@bp.route("/vehicles/<int:vehicle_id>/email-all-details", methods=["POST"])
@login_required
def email_all_details(vehicle_id):
    """Email the full vehicle details report — counterpart of the WhatsApp 'all details' link."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if not email_service.parse_emails(vehicle.owner_email):
        flash(f"No email address set for {vehicle.vehicle_number}. Edit the vehicle to add one.", "error")
        return redirect(request.referrer or url_for("vehicles.vehicle_list"))
    if not email_service.is_configured():
        flash("SMTP is not configured. Set email settings in Settings.", "error")
        return redirect(request.referrer or url_for("vehicles.vehicle_list"))
    result = email_service.send_all_vehicle_details(vehicle.owner_email, [vehicle.id])
    if result.get("ok"):
        flash(f"All details for {vehicle.vehicle_number} emailed to {vehicle.owner_email}.", "success")
    else:
        flash(f"Failed to send email: {result.get('error', 'Unknown error')}", "error")
    return redirect(request.referrer or url_for("vehicles.vehicle_list"))

@bp.route("/vehicles/email-bulk", methods=["POST"])
@login_required
def email_bulk_reminders():
    if not email_service.is_configured():
        flash("SMTP is not configured. Set email settings in Settings.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    force = request.form.get("force") == "1"
    result = email_service.send_bulk_reminders(force=force)
    flash(
        f"Consolidated reminders: {result['emails_sent']} email(s) sent to {result['total_vehicles']} vehicle(s), "
        f"{result['failed']} failed.",
        "success" if result["emails_sent"] else "error",
    )
    return redirect(url_for("vehicles.vehicle_list"))

@bp.route("/vehicles/email-selected", methods=["POST"])
@login_required
def email_selected_vehicles():
    ids = request.form.get("vehicle_ids", "")
    if not ids:
        flash("No vehicles selected.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        flash("No valid vehicle IDs.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    if not email_service.is_configured():
        flash("SMTP is not configured. Set email settings in Settings.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).all()
    result = email_service.send_consolidated_reminders(vehicles, force=True)
    flash(
        f"Consolidated reminders: {result['emails_sent']} email(s) sent to {result['total_vehicles']} vehicle(s), "
        f"{result['failed']} failed.",
        "success" if result["emails_sent"] else "error",
    )
    return redirect(url_for("vehicles.vehicle_list"))

@bp.route("/vehicles/email-vehicle-details", methods=["POST"])
@login_required
def email_all_vehicle_details():
    """Email full vehicle details to each owner — all vehicles, or only expiring ones."""
    scope = request.form.get("scope", "all")

    if not email_service.is_configured():
        flash("SMTP is not configured. Set email settings in Settings.", "error")
        return redirect(url_for("vehicles.vehicle_list"))

    vehicle_ids_raw = request.form.get("vehicle_ids", "").strip()
    if vehicle_ids_raw:
        id_list = [int(x) for x in vehicle_ids_raw.split(",") if x.strip().isdigit()]
        vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).all() if id_list else Vehicle.query.all()
    else:
        vehicles = Vehicle.query.all()

    if scope == "expiring":
        today = date.today()
        vehicles = [
            v for v in vehicles
            if any(info["expiry"] and (info["expiry"] - today).days <= 30
                   for info in v.document_statuses().values())
        ]
        if not vehicles:
            flash("No expiring vehicles found (expired or due within 30 days).", "info")
            return redirect(url_for("vehicles.vehicle_list"))

    if not vehicles:
        flash("No vehicles found.", "error")
        return redirect(url_for("vehicles.vehicle_list"))

    by_owner = {}
    for v in vehicles:
        if not v.owner_email:
            continue
        by_owner.setdefault(v.owner_email, []).append(v.id)

    if not by_owner:
        flash("No vehicles have an owner email set — nothing to send.", "error")
        return redirect(url_for("vehicles.vehicle_list"))

    sent = 0
    failed = 0
    for email_addr, v_ids in by_owner.items():
        result = email_service.send_all_vehicle_details(email_addr, v_ids)
        if result.get("ok"):
            sent += 1
        else:
            failed += 1
    skipped = len(vehicles) - sum(len(x) for x in by_owner.values())
    scope_label = "Expiring vehicle details" if scope == "expiring" else "Vehicle details"
    if sent:
        flash(f"{scope_label} sent: {sent} email(s) delivered, {failed} failed, {skipped} skipped (no email).", "success")
    else:
        flash(f"No emails sent ({failed} failed). Check SMTP settings.", "error")
    return redirect(url_for("vehicles.vehicle_list"))


