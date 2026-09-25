"""Vehicle CRUD, detail view, printing, QR codes, WhatsApp links."""
from datetime import date, datetime
import urllib.parse

from flask import (Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for)

from app.extensions import db
from app.middleware import login_required
from app.migrations import resequence_sr_nos
from app.models import (Vehicle)
from app.services import email_service
from app.services.vehicle_service import (validate_vehicle_form)
from app.utils import (generate_vehicle_qr, parse_date, to_float, whatsapp_expired_reminder, whatsapp_message)

bp = Blueprint("vehicles", __name__)

# ---- Vehicle list / search / filter ------------------------------------

@bp.route("/vehicles", strict_slashes=False)
@login_required
def vehicle_list():
    query = Vehicle.query

    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Vehicle.vehicle_number.ilike(like),
                Vehicle.chassis_number.ilike(like),
                Vehicle.engine_number.ilike(like),
                Vehicle.owner_name.ilike(like),
                Vehicle.mobile_number.ilike(like),
                Vehicle.policy_number.ilike(like),
            )
        )

    vehicle_type = request.args.get("vehicle_type", "").strip()
    if vehicle_type:
        query = query.filter(Vehicle.vehicle_type == vehicle_type)

    owner_name = request.args.get("owner_name", "").strip()
    if owner_name:
        query = query.filter(Vehicle.owner_name.ilike(f"%{owner_name}%"))

    district = request.args.get("district", "").strip()
    if district:
        query = query.filter(Vehicle.district == district)

    vehicles = query.order_by(Vehicle.vehicle_number).all()

    status_filter = request.args.get("status", "").strip()
    if status_filter:
        filtered = []
        today = date.today()
        for v in vehicles:
            statuses = v.document_statuses()
            match = False
            for info in statuses.values():
                expiry = info["expiry"]
                if expiry is None:
                    continue
                days_left = (expiry - today).days
                if status_filter == "expired" and days_left < 0:
                    match = True
                elif status_filter == "valid" and days_left >= 30:
                    match = True
                elif status_filter == "today" and days_left == 0:
                    match = True
                elif status_filter == "2days" and 0 <= days_left <= 2:
                    match = True
                elif status_filter == "7days" and 0 <= days_left <= 7:
                    match = True
                elif status_filter == "15days" and 0 <= days_left <= 15:
                    match = True
                elif status_filter == "30days" and 0 <= days_left <= 30:
                    match = True
            if match:
                filtered.append(v)
        vehicles = filtered

    vehicle_types = [r[0] for r in db.session.query(Vehicle.vehicle_type).distinct() if r[0]]
    districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
    owner_names = [r[0] for r in db.session.query(Vehicle.owner_name).distinct() if r[0]]

    session['filtered_vehicle_ids'] = [v.id for v in vehicles]

    return render_template(
        "vehicle_list.html",
        vehicles=vehicles,
        vehicle_types=vehicle_types,
        districts=districts,
        owner_names=owner_names,
        filters=request.args,
        today=date.today(),
    )

# ---- Add vehicle --------------------------------------------------------

@bp.route("/vehicles/add", methods=["GET", "POST"])
@login_required
def add_vehicle():
    if request.method == "POST":
        errors = validate_vehicle_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
            return render_template("add_vehicle.html", form=request.form, districts=districts)

        sr_no = request.form.get("sr_no", "").strip()
        if not sr_no:
            max_sr = db.session.query(db.func.max(Vehicle.sr_no)).scalar()
            if max_sr:
                next_num = int(max_sr.replace("SN", "")) + 1
            else:
                next_num = 1
            sr_no = f"SN{next_num:03d}"

        vehicle = Vehicle(
            sr_no=sr_no,
            vehicle_number=request.form["vehicle_number"].strip().upper(),
            chassis_number=request.form["chassis_number"].strip().upper(),
            engine_number=request.form.get("engine_number", "").strip().upper(),
            owner_name=request.form["owner_name"].strip(),
            mobile_number=request.form["mobile_number"].strip(),
            owner_email=email_service.normalize_emails(request.form.get("owner_email", "")),
            vehicle_type=request.form.get("vehicle_type", "").strip(),
            district=request.form.get("district", "").strip(),
            registration_date=parse_date(request.form.get("registration_date")),
            puc_expiry=parse_date(request.form.get("puc_expiry")),
            fitness_expiry=parse_date(request.form.get("fitness_expiry")),
            permit_expiry=parse_date(request.form.get("permit_expiry")),
            permit_from=parse_date(request.form.get("permit_from")),
            permit_auth_no=request.form.get("permit_auth_no", "").strip(),
            permit_address=request.form.get("permit_address", "").strip(),
            tax_from=parse_date(request.form.get("tax_from")),
            tax_expiry=parse_date(request.form.get("tax_expiry")),
            tax_mode=request.form.get("tax_mode", "").strip(),
            tax_amount=to_float(request.form.get("tax_amount")),
            insurance_expiry=parse_date(request.form.get("insurance_expiry")),
            national_permit_expiry=parse_date(request.form.get("national_permit_expiry")),
            state_permit_expiry=parse_date(request.form.get("state_permit_expiry")),
            pollution_certificate_number=request.form.get("pollution_certificate_number", "").strip(),
            insurance_company=request.form.get("insurance_company", "").strip(),
            policy_number=request.form.get("policy_number", "").strip(),
            remarks=request.form.get("remarks", "").strip(),
        )
        db.session.add(vehicle)
        db.session.commit()
        flash(f"Vehicle {vehicle.vehicle_number} added successfully.", "success")
        return redirect(url_for("vehicles.vehicle_list"))

    districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
    return render_template("add_vehicle.html", form={}, districts=districts)

# ---- Edit vehicle --------------------------------------------------------

@bp.route("/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@login_required
def edit_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if request.method == "POST":
        errors = validate_vehicle_form(request.form, editing_id=vehicle_id)
        if errors:
            for e in errors:
                flash(e, "error")
            districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
            return render_template("edit_vehicle.html", vehicle=vehicle, form=request.form, districts=districts)

        vehicle.vehicle_number = request.form["vehicle_number"].strip().upper()
        vehicle.chassis_number = request.form["chassis_number"].strip().upper()
        vehicle.engine_number = request.form.get("engine_number", "").strip().upper()
        vehicle.owner_name = request.form["owner_name"].strip()
        vehicle.mobile_number = request.form["mobile_number"].strip()
        vehicle.owner_email = email_service.normalize_emails(request.form.get("owner_email", ""))
        vehicle.vehicle_type = request.form.get("vehicle_type", "").strip()
        vehicle.district = request.form.get("district", "").strip()
        vehicle.registration_date = parse_date(request.form.get("registration_date"))
        vehicle.puc_expiry = parse_date(request.form.get("puc_expiry"))
        vehicle.fitness_expiry = parse_date(request.form.get("fitness_expiry"))
        vehicle.permit_expiry = parse_date(request.form.get("permit_expiry"))
        vehicle.permit_from = parse_date(request.form.get("permit_from"))
        vehicle.permit_auth_no = request.form.get("permit_auth_no", "").strip()
        vehicle.permit_address = request.form.get("permit_address", "").strip()
        vehicle.tax_from = parse_date(request.form.get("tax_from"))
        vehicle.tax_expiry = parse_date(request.form.get("tax_expiry"))
        vehicle.tax_mode = request.form.get("tax_mode", "").strip()
        vehicle.tax_amount = to_float(request.form.get("tax_amount"))
        vehicle.insurance_expiry = parse_date(request.form.get("insurance_expiry"))
        vehicle.national_permit_expiry = parse_date(request.form.get("national_permit_expiry"))
        vehicle.state_permit_expiry = parse_date(request.form.get("state_permit_expiry"))
        vehicle.pollution_certificate_number = request.form.get("pollution_certificate_number", "").strip()
        vehicle.insurance_company = request.form.get("insurance_company", "").strip()
        vehicle.policy_number = request.form.get("policy_number", "").strip()
        vehicle.remarks = request.form.get("remarks", "").strip()
        vehicle.updated_at = datetime.utcnow()

        db.session.commit()
        flash(f"Vehicle {vehicle.vehicle_number} updated successfully.", "success")
        return redirect(url_for("vehicles.vehicle_list"))

    districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
    return render_template("edit_vehicle.html", vehicle=vehicle, form=vehicle.to_dict(), districts=districts)

@bp.route("/vehicles/delete-all", methods=["POST"])
@login_required
def delete_all_vehicles():
    count = Vehicle.query.count()
    Vehicle.query.delete()
    try:
        db.session.execute(db.text("DELETE FROM sqlite_sequence WHERE name='vehicles'"))
    except Exception:
        pass
    db.session.commit()
    flash(f"All {count} vehicles deleted.", "success")
    return redirect(url_for("vehicles.vehicle_list"))

@bp.route("/vehicles/<int:vehicle_id>/delete", methods=["POST"])
@login_required
def delete_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    number = vehicle.vehicle_number
    db.session.delete(vehicle)
    db.session.commit()
    resequence_sr_nos()
    flash(f"Vehicle {number} deleted.", "success")
    return redirect(url_for("vehicles.vehicle_list"))

@bp.route("/vehicles/<int:vehicle_id>")
@login_required
def view_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    filtered_ids = session.get('filtered_vehicle_ids', [])
    if filtered_ids and vehicle_id in filtered_ids:
        idx = filtered_ids.index(vehicle_id)
        prev_id = filtered_ids[idx - 1] if idx > 0 else None
        next_id = filtered_ids[idx + 1] if idx < len(filtered_ids) - 1 else None
        prev_vehicle = Vehicle.query.get(prev_id) if prev_id else None
        next_vehicle = Vehicle.query.get(next_id) if next_id else None
    else:
        prev_vehicle = Vehicle.query.filter(Vehicle.id < vehicle_id).order_by(Vehicle.id.desc()).first()
        next_vehicle = Vehicle.query.filter(Vehicle.id > vehicle_id).order_by(Vehicle.id.asc()).first()
    return render_template("view_vehicle.html", vehicle=vehicle, prev_vehicle=prev_vehicle, next_vehicle=next_vehicle, today=date.today())

@bp.route("/vehicles/<int:vehicle_id>/print")
@login_required
def print_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    statuses = vehicle.document_statuses()
    valid_count = sum(1 for s in statuses.values() if s["class"] == "status-green")
    total = len(statuses)
    overall = vehicle.overall_status()
    if overall == "status-green":
        badge_label, badge_color = "Excellent", "#22c55e"
    elif overall == "status-yellow":
        badge_label, badge_color = "Renewal Due", "#eab308"
    elif overall == "status-orange":
        badge_label, badge_color = "Urgent", "#f97316"
    elif overall == "status-red":
        badge_label, badge_color = "Action Required", "#ef4444"
    else:
        badge_label, badge_color = "No Data", "#6b7280"
    return render_template(
        "print_vehicle.html",
        vehicle=vehicle,
        statuses=statuses,
        valid_count=valid_count,
        total=total,
        badge_label=badge_label,
        badge_color=badge_color,
    )

@bp.route("/vehicles/print")
@login_required
def print_vehicles():
    ids_param = request.args.get("ids", "")
    if not ids_param:
        flash("No vehicles selected for printing.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    id_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    if not id_list:
        flash("No valid vehicles selected.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).order_by(Vehicle.vehicle_number).all()
    vehicle_data = []
    for v in vehicles:
        statuses = v.document_statuses()
        valid_count = sum(1 for s in statuses.values() if s["class"] == "status-green")
        total = len(statuses)
        overall = v.overall_status()
        if overall == "status-green":
            badge_label, badge_color = "Excellent", "#22c55e"
        elif overall == "status-yellow":
            badge_label, badge_color = "Renewal Due", "#eab308"
        elif overall == "status-orange":
            badge_label, badge_color = "Urgent", "#f97316"
        elif overall == "status-red":
            badge_label, badge_color = "Action Required", "#ef4444"
        else:
            badge_label, badge_color = "No Data", "#6b7280"
        vehicle_data.append({
            "vehicle": v,
            "statuses": statuses,
            "valid_count": valid_count,
            "total": total,
            "badge_label": badge_label,
            "badge_color": badge_color,
        })
    return render_template("print_vehicles.html", vehicle_data=vehicle_data)

@bp.route("/vehicles/print-qr")
@login_required
def print_qr():
    ids_param = request.args.get("ids", "")
    if not ids_param:
        flash("No vehicles selected for QR printing.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    id_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    if not id_list:
        flash("No valid vehicles selected.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).order_by(Vehicle.vehicle_number).all()
    pages = [vehicles[i:i+6] for i in range(0, len(vehicles), 6)]
    return render_template("print_qr.html", pages=pages)

@bp.route("/vehicles/<int:vehicle_id>/qr")
@login_required
def vehicle_qr(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    qr_buffer = generate_vehicle_qr(vehicle)
    return send_file(qr_buffer, mimetype="image/png", download_name=f"qr_{vehicle.vehicle_number}.png")

@bp.route("/vehicles/<int:vehicle_id>/qr-dates")
@login_required
def vehicle_qr_dates(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    statuses = vehicle.document_statuses()
    return render_template("vehicle_qr_dates.html", vehicle=vehicle, statuses=statuses, today=date.today())

# ---- WhatsApp reminder helper -------------------------------------------

@bp.route("/vehicles/<int:vehicle_id>/whatsapp/<document_label>")
@login_required
def whatsapp_reminder(vehicle_id, document_label):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if document_label == "all":
        message = whatsapp_message(vehicle, None, None)
    else:
        field = Vehicle.DOCUMENT_FIELDS.get(document_label)
        if not field:
            abort(404)
        expiry = getattr(vehicle, field)
        if not expiry:
            flash("No expiry date set for this document.", "error")
            return redirect(url_for("vehicles.vehicle_list"))
        message = whatsapp_message(vehicle, document_label, expiry)
    wa_link = f"https://wa.me/{vehicle.mobile_number}?text={urllib.parse.quote(message)}"
    return redirect(wa_link)

@bp.route("/vehicles/<int:vehicle_id>/whatsapp-expired")
@login_required
def whatsapp_expired(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    message = whatsapp_expired_reminder(vehicle)
    if not message:
        flash("No expired or expiring documents found for this vehicle.", "error")
        return redirect(url_for("vehicles.vehicle_list"))
    wa_link = f"https://wa.me/{vehicle.mobile_number}?text={urllib.parse.quote(message)}"
    return redirect(wa_link)


