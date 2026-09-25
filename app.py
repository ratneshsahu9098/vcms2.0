import io
import json
import logging
import os
import shutil
import urllib.parse
from datetime import date, timedelta, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, send_file, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd

from config import Config
from models import db, Vehicle, TaxDetail, ChatSession, ChatMessage, ReminderLog, DocumentScan
from utils import (
    parse_date, allowed_file, normalize_import_dataframe,
    create_backup, restore_backup, list_backups, whatsapp_message, whatsapp_expired_reminder, generate_vehicle_qr
)
import ai_service
import email_service
import google_drive

try:
    from flask_apscheduler import APScheduler
except ImportError:
    APScheduler = None

logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    for folder in (app.config["UPLOAD_FOLDER"], app.config["EXPORT_FOLDER"], app.config["BACKUP_FOLDER"]):
        os.makedirs(folder, exist_ok=True)

    with app.app_context():
        db.create_all()
        run_migrations()
        resequence_sr_nos()
        start_scheduler(app)

    register_routes(app)
    return app


def run_migrations():
    """Lightweight SQLite migrations for columns added after first release."""
    try:
        inspector = db.inspect(db.engine)
        table_names = inspector.get_table_names()
        if "vehicles" not in table_names:
            return
        migrations = [
            ("vehicles", "owner_email", "VARCHAR(255)"),
            ("vehicles", "permit_from", "DATE"),
            ("vehicles", "permit_auth_no", "VARCHAR(50)"),
            ("vehicles", "permit_address", "VARCHAR(255)"),
            ("reminder_logs", "kind", "VARCHAR(20)"),
        ]
        with db.engine.begin() as conn:
            for table, column, col_type in migrations:
                existing_cols = [c["name"] for c in inspector.get_columns(table)]
                if column not in existing_cols:
                    try:
                        conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        logger.info(f"Migration: added {table}.{column}")
                    except Exception as e:
                        logger.warning(f"Migration skipped {table}.{column}: {e}")

        # reminder_logs: backfill kind for old rows and make vehicle_id nullable
        # (manual detail emails / tests are not tied to a single vehicle).
        try:
            if "reminder_logs" in table_names:
                cols = {c["name"]: c for c in db.inspect(db.engine).get_columns("reminder_logs")}
                if "kind" in cols:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("UPDATE reminder_logs SET kind = 'reminder' WHERE kind IS NULL"))
                    logger.info("Migration: reminder_logs.kind backfilled")
                vc = cols.get("vehicle_id")
                if vc is not None and not vc.get("nullable", True):
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE reminder_logs RENAME TO reminder_logs_old"))
                        conn.execute(db.text(
                            "CREATE TABLE reminder_logs ("
                            "id INTEGER NOT NULL PRIMARY KEY, "
                            "vehicle_id INTEGER, "
                            "document_type VARCHAR(30) NOT NULL, "
                            "recipient_email VARCHAR(120) NOT NULL, "
                            "status VARCHAR(20), "
                            "error_message TEXT, "
                            "sent_at DATETIME, "
                            "kind VARCHAR(20), "
                            "FOREIGN KEY(vehicle_id) REFERENCES vehicles (id))"
                        ))
                        conn.execute(db.text(
                            "INSERT INTO reminder_logs (id, vehicle_id, document_type, recipient_email,"
                            " status, error_message, sent_at, kind)"
                            " SELECT id, vehicle_id, document_type, recipient_email,"
                            " status, error_message, sent_at, kind FROM reminder_logs_old"
                        ))
                        conn.execute(db.text("DROP TABLE reminder_logs_old"))
                    logger.info("Migration: reminder_logs.vehicle_id is now nullable")
        except Exception as e:
            logger.warning(f"Migration skipped reminder_logs rebuild: {e}")
    except Exception as e:
        logger.warning(f"Migration check failed: {e}")


def start_scheduler(app):
    """Daily auto email reminders via APScheduler (optional dependency)."""
    if APScheduler is None:
        logger.info("Flask-APScheduler not installed; daily auto-reminders disabled.")
        return
    if app.config.get("TESTING"):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return  # avoid double-start under the Werkzeug reloader parent process

    app.config.setdefault("SCHEDULER_API_ENABLED", False)

    scheduler = APScheduler()
    scheduler.init_app(app)

    @scheduler.task("cron", id="daily_email_reminders",
                    hour=app.config.get("EMAIL_REMINDER_HOUR", 9), minute=0)
    def daily_email_reminders():
        with app.app_context():
            from utils import load_settings
            settings = load_settings()
            if not settings.get("auto_reminders_enabled", False):
                return
            try:
                result = email_service.auto_reminder_job()
                logger.info(f"Auto-reminder job: {result}")
            except Exception:
                logger.exception("Auto-reminder job failed")

    try:
        scheduler.start()
        logger.info(f"Scheduler started: daily email reminders at {app.config.get('EMAIL_REMINDER_HOUR', 9)}:00")
    except Exception:
        logger.exception("Scheduler failed to start")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if Config.LOGIN_REQUIRED and not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def resequence_sr_nos():
    vehicles = Vehicle.query.order_by(Vehicle.vehicle_number).all()
    for i, v in enumerate(vehicles, 1):
        v.sr_no = f"SN{i:03d}"
    db.session.commit()


def find_existing_vehicle(parsed_data):
    vnum = str(parsed_data.get("vehicle_number") or "").strip().upper()
    chassis = str(parsed_data.get("chassis_number") or "").strip().upper()
    if not vnum and not chassis:
        return None
    return Vehicle.query.filter(
        db.or_(Vehicle.vehicle_number == vnum, Vehicle.chassis_number == chassis)
    ).first()


def recent_document_scans(limit=5):
    return DocumentScan.query.order_by(
        DocumentScan.scanned_at.desc(), DocumentScan.id.desc()
    ).limit(limit).all()


def save_document_scan(file_name, parsed_data, ocr_text, existing_vehicle=None):
    scan = DocumentScan(
        file_name=file_name,
        document_type=str(parsed_data.get("document_type") or ""),
        parsed_data=json.dumps(parsed_data, default=str),
        ocr_text=ocr_text,
        vehicle_id=existing_vehicle.id if existing_vehicle else None,
    )
    db.session.add(scan)
    db.session.commit()
    prune_document_scans()
    return scan


def prune_document_scans(keep=20):
    stale = DocumentScan.query.order_by(
        DocumentScan.scanned_at.desc(), DocumentScan.id.desc()
    ).offset(keep).all()
    for s in stale:
        db.session.delete(s)
    if stale:
        db.session.commit()


EXPORT_COLUMNS = [
    ("vehicle_number", "Vehicle Number"),
    ("chassis_number", "Chassis Number"),
    ("engine_number", "Engine Number"),
    ("owner_name", "Owner Name"),
    ("mobile_number", "Mobile Number"),
    ("owner_email", "Owner Email"),
    ("vehicle_type", "Vehicle Type"),
    ("district", "District"),
    ("registration_date", "Registration Date"),
    ("puc_expiry", "PUC Expiry"),
    ("fitness_expiry", "Fitness Expiry"),
    ("permit_expiry", "Permit Expiry"),
    ("permit_from", "Permit From"),
    ("permit_auth_no", "Permit Auth No."),
    ("permit_address", "Address"),
    ("tax_expiry", "Tax Expiry"),
    ("tax_from", "Tax From"),
    ("tax_mode", "Tax Mode"),
    ("tax_amount", "Tax Amount"),
    ("insurance_expiry", "Insurance Expiry"),
    ("national_permit_expiry", "National Permit Expiry"),
    ("state_permit_expiry", "State Permit Expiry"),
    ("insurance_company", "Insurance Company"),
    ("policy_number", "Policy Number"),
    ("pollution_certificate_number", "Pollution Cert. No."),
    ("remarks", "Remarks"),
    ("created_at", "Created At"),
    ("updated_at", "Updated At"),
]


def register_routes(app):

    # ---- Auth ------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not Config.LOGIN_REQUIRED:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
                session["logged_in"] = True
                session["username"] = username
                flash("Welcome back!", "success")
                next_url = request.args.get("next") or url_for("dashboard")
                return redirect(next_url)
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    # ---- Dashboard ---------------------------------------------------------

    @app.route("/")
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

    # ---- Vehicle list / search / filter ------------------------------------

    @app.route("/vehicles", strict_slashes=False)
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

    @app.route("/vehicles/add", methods=["GET", "POST"])
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
                tax_amount=float(request.form.get("tax_amount", 0) or 0),
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
            return redirect(url_for("vehicle_list"))

        districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
        return render_template("add_vehicle.html", form={}, districts=districts)

    # ---- Edit vehicle --------------------------------------------------------

    @app.route("/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
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
            vehicle.tax_amount = float(request.form.get("tax_amount", 0) or 0)
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
            return redirect(url_for("vehicle_list"))

        districts = [r[0] for r in db.session.query(Vehicle.district).distinct() if r[0]]
        return render_template("edit_vehicle.html", vehicle=vehicle, form=vehicle.to_dict(), districts=districts)

    @app.route("/vehicles/delete-all", methods=["POST"])
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
        return redirect(url_for("vehicle_list"))

    @app.route("/vehicles/<int:vehicle_id>/delete", methods=["POST"])
    @login_required
    def delete_vehicle(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        number = vehicle.vehicle_number
        db.session.delete(vehicle)
        db.session.commit()
        resequence_sr_nos()
        flash(f"Vehicle {number} deleted.", "success")
        return redirect(url_for("vehicle_list"))

    @app.route("/vehicles/<int:vehicle_id>")
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

    @app.route("/vehicles/<int:vehicle_id>/print")
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

    @app.route("/vehicles/print")
    @login_required
    def print_vehicles():
        ids_param = request.args.get("ids", "")
        if not ids_param:
            flash("No vehicles selected for printing.", "error")
            return redirect(url_for("vehicle_list"))
        id_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
        if not id_list:
            flash("No valid vehicles selected.", "error")
            return redirect(url_for("vehicle_list"))
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

    @app.route("/vehicles/print-qr")
    @login_required
    def print_qr():
        ids_param = request.args.get("ids", "")
        if not ids_param:
            flash("No vehicles selected for QR printing.", "error")
            return redirect(url_for("vehicle_list"))
        id_list = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
        if not id_list:
            flash("No valid vehicles selected.", "error")
            return redirect(url_for("vehicle_list"))
        vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).order_by(Vehicle.vehicle_number).all()
        pages = [vehicles[i:i+6] for i in range(0, len(vehicles), 6)]
        return render_template("print_qr.html", pages=pages)

    @app.route("/vehicles/<int:vehicle_id>/qr")
    @login_required
    def vehicle_qr(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        qr_buffer = generate_vehicle_qr(vehicle)
        return send_file(qr_buffer, mimetype="image/png", download_name=f"qr_{vehicle.vehicle_number}.png")

    @app.route("/vehicles/<int:vehicle_id>/qr-dates")
    @login_required
    def vehicle_qr_dates(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        statuses = vehicle.document_statuses()
        return render_template("vehicle_qr_dates.html", vehicle=vehicle, statuses=statuses, today=date.today())

    # ---- WhatsApp reminder helper -------------------------------------------

    @app.route("/vehicles/<int:vehicle_id>/whatsapp/<document_label>")
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
                return redirect(url_for("vehicle_list"))
            message = whatsapp_message(vehicle, document_label, expiry)
        wa_link = f"https://wa.me/{vehicle.mobile_number}?text={urllib.parse.quote(message)}"
        return redirect(wa_link)

    @app.route("/vehicles/<int:vehicle_id>/whatsapp-expired")
    @login_required
    def whatsapp_expired(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        message = whatsapp_expired_reminder(vehicle)
        if not message:
            flash("No expired or expiring documents found for this vehicle.", "error")
            return redirect(url_for("vehicle_list"))
        wa_link = f"https://wa.me/{vehicle.mobile_number}?text={urllib.parse.quote(message)}"
        return redirect(wa_link)

    # ---- Email reminders (SMTP) ----------------------------------------------

    @app.route("/vehicles/<int:vehicle_id>/email-reminder", methods=["POST"])
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
        return redirect(request.referrer or url_for("view_vehicle", vehicle_id=vehicle.id))

    @app.route("/vehicles/<int:vehicle_id>/email-all-details", methods=["POST"])
    @login_required
    def email_all_details(vehicle_id):
        """Email the full vehicle details report — counterpart of the WhatsApp 'all details' link."""
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        if not email_service.parse_emails(vehicle.owner_email):
            flash(f"No email address set for {vehicle.vehicle_number}. Edit the vehicle to add one.", "error")
            return redirect(request.referrer or url_for("vehicle_list"))
        if not email_service.is_configured():
            flash("SMTP is not configured. Set email settings in Settings.", "error")
            return redirect(request.referrer or url_for("vehicle_list"))
        result = email_service.send_all_vehicle_details(vehicle.owner_email, [vehicle.id])
        if result.get("ok"):
            flash(f"All details for {vehicle.vehicle_number} emailed to {vehicle.owner_email}.", "success")
        else:
            flash(f"Failed to send email: {result.get('error', 'Unknown error')}", "error")
        return redirect(request.referrer or url_for("vehicle_list"))

    @app.route("/vehicles/email-bulk", methods=["POST"])
    @login_required
    def email_bulk_reminders():
        if not email_service.is_configured():
            flash("SMTP is not configured. Set email settings in Settings.", "error")
            return redirect(url_for("vehicle_list"))
        force = request.form.get("force") == "1"
        result = email_service.send_bulk_reminders(force=force)
        flash(
            f"Consolidated reminders: {result['emails_sent']} email(s) sent to {result['total_vehicles']} vehicle(s), "
            f"{result['failed']} failed.",
            "success" if result["emails_sent"] else "error",
        )
        return redirect(url_for("vehicle_list"))

    @app.route("/vehicles/email-selected", methods=["POST"])
    @login_required
    def email_selected_vehicles():
        ids = request.form.get("vehicle_ids", "")
        if not ids:
            flash("No vehicles selected.", "error")
            return redirect(url_for("vehicle_list"))
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        if not id_list:
            flash("No valid vehicle IDs.", "error")
            return redirect(url_for("vehicle_list"))
        if not email_service.is_configured():
            flash("SMTP is not configured. Set email settings in Settings.", "error")
            return redirect(url_for("vehicle_list"))
        vehicles = Vehicle.query.filter(Vehicle.id.in_(id_list)).all()
        result = email_service.send_consolidated_reminders(vehicles, force=True)
        flash(
            f"Consolidated reminders: {result['emails_sent']} email(s) sent to {result['total_vehicles']} vehicle(s), "
            f"{result['failed']} failed.",
            "success" if result["emails_sent"] else "error",
        )
        return redirect(url_for("vehicle_list"))

    @app.route("/vehicles/email-vehicle-details", methods=["POST"])
    @login_required
    def email_all_vehicle_details():
        """Email full vehicle details to each owner — all vehicles, or only expiring ones."""
        scope = request.form.get("scope", "all")

        if not email_service.is_configured():
            flash("SMTP is not configured. Set email settings in Settings.", "error")
            return redirect(url_for("vehicle_list"))

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
                return redirect(url_for("vehicle_list"))

        if not vehicles:
            flash("No vehicles found.", "error")
            return redirect(url_for("vehicle_list"))

        by_owner = {}
        for v in vehicles:
            if not v.owner_email:
                continue
            by_owner.setdefault(v.owner_email, []).append(v.id)

        if not by_owner:
            flash("No vehicles have an owner email set — nothing to send.", "error")
            return redirect(url_for("vehicle_list"))

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
        return redirect(url_for("vehicle_list"))

    @app.route("/reminders")
    @login_required
    def reminder_logs():
        page = request.args.get("page", 1, type=int)
        status_filter = request.args.get("status", "").strip()
        kind_filter = request.args.get("kind", "").strip()
        per_page = 50
        query = ReminderLog.query.order_by(ReminderLog.sent_at.desc())
        if status_filter in ("sent", "failed"):
            query = query.filter_by(status=status_filter)
        if kind_filter in ("reminder", "details", "test"):
            query = query.filter_by(kind=kind_filter)
        logs = query.paginate(page=page, per_page=per_page, error_out=False)
        return render_template("reminders.html", logs=logs)

    @app.route("/reminders/clear", methods=["POST"])
    @login_required
    def clear_reminder_logs():
        ReminderLog.query.delete()
        db.session.commit()
        flash("Reminder logs cleared.", "success")
        return redirect(url_for("reminder_logs"))

    # ---- Excel Import --------------------------------------------------------

    @app.route("/import", methods=["GET", "POST"])
    @login_required
    def import_excel():
        if request.method == "POST":
            file = request.files.get("file")
            if not file or file.filename == "":
                flash("Please choose a file to import.", "error")
                return redirect(url_for("import_excel"))

            if not allowed_file(file.filename, Config.ALLOWED_IMPORT_EXTENSIONS):
                flash("Unsupported file type. Please upload .xlsx, .xls, .csv, or .json", "error")
                return redirect(url_for("import_excel"))

            try:
                if file.filename.lower().endswith(".json"):
                    raw = json.load(file)
                elif file.filename.lower().endswith(".csv"):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
            except Exception as exc:
                flash(f"Could not read file: {exc}", "error")
                return redirect(url_for("import_excel"))

            duplicate_action = request.form.get("duplicate_action", "skip")
            imported, updated, skipped, errors = 0, 0, 0, []

            if file.filename.lower().endswith(".json"):
                if not isinstance(raw, list):
                    flash("JSON file must contain an array of vehicle objects.", "error")
                    return redirect(url_for("import_excel"))
                for idx, record in enumerate(raw):
                    vnum = str(record.get("vehicle_number", "")).strip().upper()
                    chassis = str(record.get("chassis_number", "")).strip().upper()
                    if not vnum or not chassis or vnum.lower() == "nan":
                        skipped += 1
                        errors.append(f"Record {idx + 1}: missing vehicle/chassis number")
                        continue
                    existing = Vehicle.query.filter(
                        db.or_(Vehicle.vehicle_number == vnum, Vehicle.chassis_number == chassis)
                    ).first()
                    if existing:
                        if duplicate_action == "update":
                            update_vehicle_from_record(existing, record)
                            updated += 1
                        else:
                            skipped += 1
                            errors.append(f"Record {idx + 1}: duplicate vehicle {vnum}")
                        continue
                    vehicle = Vehicle(
                        vehicle_number=vnum,
                        chassis_number=chassis,
                        engine_number=str(record.get("engine_number", "")).strip().upper(),
                        owner_name=str(record.get("owner_name", "")).strip(),
                        mobile_number=str(record.get("mobile_number", "")).strip(),
                        owner_email=email_service.normalize_emails(str(record.get("owner_email", "") or "")),
                        vehicle_type=str(record.get("vehicle_type", "")).strip(),
                        district=str(record.get("district", "")).strip(),
                        registration_date=parse_date(record.get("registration_date")),
                        puc_expiry=parse_date(record.get("puc_expiry")),
                        fitness_expiry=parse_date(record.get("fitness_expiry")),
                        permit_expiry=parse_date(record.get("permit_expiry")),
                        tax_from=parse_date(record.get("tax_from")),
                        tax_expiry=parse_date(record.get("tax_expiry")),
                        tax_mode=str(record.get("tax_mode", "")).strip(),
                        tax_amount=float(record.get("tax_amount", 0) or 0),
                        insurance_expiry=parse_date(record.get("insurance_expiry")),
                        national_permit_expiry=parse_date(record.get("national_permit_expiry")),
                        state_permit_expiry=parse_date(record.get("state_permit_expiry")),
                        pollution_certificate_number=str(record.get("pollution_certificate_number", "")).strip(),
                        insurance_company=str(record.get("insurance_company", "")).strip(),
                        policy_number=str(record.get("policy_number", "")).strip(),
                        remarks=str(record.get("remarks", "")).strip(),
                    )
                    db.session.add(vehicle)
                    imported += 1
            else:
                df = normalize_import_dataframe(df)
                required_cols = {"vehicle_number", "chassis_number", "owner_name", "mobile_number"}
                missing = required_cols - set(df.columns)
                if missing:
                    flash(f"Missing required columns: {', '.join(missing)}", "error")
                    return redirect(url_for("import_excel"))

                for idx, row in df.iterrows():
                    vnum = str(row.get("vehicle_number", "")).strip().upper()
                    chassis = str(row.get("chassis_number", "")).strip().upper()
                    if not vnum or not chassis or vnum.lower() == "nan":
                        skipped += 1
                        errors.append(f"Row {idx + 2}: missing vehicle/chassis number")
                        continue
                    existing = Vehicle.query.filter(
                        db.or_(Vehicle.vehicle_number == vnum, Vehicle.chassis_number == chassis)
                    ).first()
                    if existing:
                        if duplicate_action == "update":
                            update_vehicle_from_record(existing, row)
                            updated += 1
                        else:
                            skipped += 1
                            errors.append(f"Row {idx + 2}: duplicate vehicle {vnum}")
                        continue

                    vehicle = Vehicle(
                        vehicle_number=vnum,
                        chassis_number=chassis,
                        engine_number=str(row.get("engine_number", "")).strip().upper(),
                        owner_name=str(row.get("owner_name", "")).strip(),
                        mobile_number=str(row.get("mobile_number", "")).strip(),
                        owner_email=email_service.normalize_emails(str(row.get("owner_email", "") or "")),
                        vehicle_type=str(row.get("vehicle_type", "")).strip(),
                        district=str(row.get("district", "")).strip(),
                        registration_date=parse_date(row.get("registration_date")),
                        puc_expiry=parse_date(row.get("puc_expiry")),
                        fitness_expiry=parse_date(row.get("fitness_expiry")),
                        permit_expiry=parse_date(row.get("permit_expiry")),
                        tax_from=parse_date(row.get("tax_from")),
                        tax_expiry=parse_date(row.get("tax_expiry")),
                        tax_mode=str(row.get("tax_mode", "")).strip(),
                        tax_amount=float(row.get("tax_amount", 0) or 0),
                        insurance_expiry=parse_date(row.get("insurance_expiry")),
                        national_permit_expiry=parse_date(row.get("national_permit_expiry")),
                        state_permit_expiry=parse_date(row.get("state_permit_expiry")),
                        pollution_certificate_number=str(row.get("pollution_certificate_number", "")).strip(),
                        insurance_company=str(row.get("insurance_company", "")).strip(),
                        policy_number=str(row.get("policy_number", "")).strip(),
                        remarks=str(row.get("remarks", "")).strip(),
                    )
                    db.session.add(vehicle)
                    imported += 1

            db.session.commit()
            resequence_sr_nos()
            if updated:
                flash(f"Import complete: {imported} added, {updated} updated, {skipped} skipped.", "success" if imported or updated else "error")
            else:
                flash(f"Import complete: {imported} added, {skipped} skipped.", "success" if imported else "error")
            if errors:
                session["import_errors"] = errors[:20]
            return redirect(url_for("import_excel"))

        import_errors = session.pop("import_errors", [])
        return render_template("import_excel.html", import_errors=import_errors)

    # ---- Excel Export --------------------------------------------------------

    @app.route("/export")
    @login_required
    def export_excel():
        owners = [r[0] for r in db.session.query(Vehicle.owner_name).distinct().order_by(Vehicle.owner_name) if r[0]]
        return render_template("export_excel.html", export_columns=EXPORT_COLUMNS, owners=owners)

    @app.route("/export/run")
    @login_required
    def export_run():
        scope = request.args.get("scope", "all")
        file_format = request.args.get("format", "xlsx")
        selected_columns = request.args.getlist("columns")
        owner_filter = request.args.get("owner_name", "").strip()
        today = date.today()

        vehicles = Vehicle.query.all()

        if owner_filter:
            vehicles = [v for v in vehicles if v.owner_name == owner_filter]

        if scope == "owner_vehicle":
            selected_columns = ["owner_name", "vehicle_number"]
        elif scope == "expired":
            vehicles = [v for v in vehicles if v.overall_status() == "status-red"]
        elif scope == "due7":
            vehicles = [v for v in vehicles if any(
                info["expiry"] and 0 <= (info["expiry"] - today).days <= 7
                for info in v.document_statuses().values()
            )]
        elif scope == "due30":
            vehicles = [v for v in vehicles if any(
                info["expiry"] and 0 <= (info["expiry"] - today).days <= 30
                for info in v.document_statuses().values()
            )]
        elif scope == "custom":
            start = parse_date(request.args.get("start"))
            end = parse_date(request.args.get("end"))
            if start and end:
                vehicles = [v for v in vehicles if any(
                    info["expiry"] and start <= info["expiry"] <= end
                    for info in v.document_statuses().values()
                )]

        data = [v.to_dict() for v in vehicles]

        if selected_columns:
            filtered = []
            for row in data:
                ordered = {}
                for col in selected_columns:
                    if col in row:
                        ordered[col] = row[col]
                filtered.append(ordered)
            data = filtered

        buffer = io.BytesIO()
        scope_names = {
            "all": "All_Vehicles", "owner_vehicle": "Owner_Vehicle_List",
            "expired": "Expired", "due7": "Due_in_7_Days", "due30": "Due_in_30_Days",
        }
        label = scope_names.get(scope, scope.capitalize())
        if scope == "custom":
            s = request.args.get("start", "")[:10]
            e = request.args.get("end", "")[:10]
            label = f"Custom_{s}_to_{e}" if s and e else "Custom_Range"
        if owner_filter:
            label = owner_filter.replace(" ", "_") + "_" + label
        compliance_preset = {"vehicle_number", "chassis_number", "puc_expiry", "fitness_expiry", "tax_expiry"}
        if set(selected_columns) == compliance_preset and scope != "owner_vehicle":
            label += "_Compliance_Summary"
        filename = f"{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if file_format == "json":
            buffer.write(json.dumps(data, indent=2).encode("utf-8"))
            mimetype = "application/json"
            filename += ".json"
        elif file_format == "csv":
            df = pd.DataFrame(data)
            df.to_csv(buffer, index=False)
            mimetype = "text/csv"
            filename += ".csv"
        else:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                pd.DataFrame(data).to_excel(writer, index=False, sheet_name="Vehicles")
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename += ".xlsx"

        buffer.seek(0)
        return send_file(buffer, mimetype=mimetype, as_attachment=True, download_name=filename)

    # ---- Reports --------------------------------------------------------------

    @app.route("/reports")
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

    # ---- Backup / Restore -------------------------------------------------

    @app.route("/backup", methods=["GET", "POST"])
    @login_required
    def backup():
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
        if request.method == "POST":
            action = request.form.get("action")
            if action == "create":
                name, _ = create_backup(db_path, app.config["BACKUP_FOLDER"])
                flash(f"Backup created: {name} (database + settings, API keys and models)", "success")
            elif action == "restore":
                backup_name = request.form.get("backup_name")
                backup_path = os.path.join(app.config["BACKUP_FOLDER"], backup_name)
                if os.path.exists(backup_path):
                    db.session.remove()
                    db.engine.dispose()
                    result = restore_backup(backup_path, db_path)
                    if result["ok"]:
                        flash(f"{result['message']} ({backup_name})", "success")
                    else:
                        flash(result["message"], "error")
                else:
                    flash("Backup file not found.", "error")
            elif action == "upload_restore":
                file = request.files.get("backup_file")
                if file and file.filename:
                    filename = file.filename.strip()
                    if not filename.endswith(".db") and not filename.endswith(".zip"):
                        flash("Only .db or .zip backup files are allowed.", "error")
                    else:
                        upload_path = os.path.join(app.config["BACKUP_FOLDER"], f"upload_{filename}")
                        file.save(upload_path)
                        db.session.remove()
                        db.engine.dispose()
                        result = restore_backup(upload_path, db_path)
                        os.remove(upload_path)
                        if result["ok"]:
                            flash(f"{result['message']} (uploaded: {filename})", "success")
                        else:
                            flash(result["message"], "error")
                else:
                    flash("No file selected.", "error")
            return redirect(url_for("backup"))

        from utils import load_settings
        backups = list_backups(app.config["BACKUP_FOLDER"])
        gdrive_backups = google_drive.list_backups()
        gdrive_connected = google_drive.is_connected()
        app_settings = load_settings()
        return render_template("backup.html", backups=backups,
                               gdrive_backups=gdrive_backups, gdrive_connected=gdrive_connected,
                               app_settings=app_settings)

    @app.route("/backup/download/<name>")
    @login_required
    def download_backup(name):
        path = os.path.join(app.config["BACKUP_FOLDER"], name)
        if not os.path.exists(path):
            abort(404)
        return send_file(path, as_attachment=True, download_name=name)

    # ---- Google Drive Sync ------------------------------------------------

    @app.route("/settings/google/connect")
    @login_required
    def gdrive_connect():
        flow, error = google_drive.start_oauth_flow()
        if error:
            flash(error, "error")
            return redirect(url_for("settings"))
        redirect_uri = url_for("gdrive_callback", _external=True)
        auth_url, _ = flow.authorization_url(prompt="consent", redirect_uri=redirect_uri)
        return redirect(auth_url)

    @app.route("/settings/google/callback")
    def gdrive_callback():
        from utils import load_settings, save_settings
        code = request.args.get("code")
        if not code:
            flash("Google Drive authorization failed.", "error")
            return redirect(url_for("settings"))
        redirect_uri = url_for("gdrive_callback", _external=True)
        result = google_drive.save_token_from_code(code, redirect_uri)
        if result.get("ok"):
            email = google_drive.get_user_email()
            settings = load_settings()
            settings["gdrive_user_email"] = email or ""
            save_settings(settings)
            flash(f"Google Drive connected as {email or 'unknown'}", "success")
        else:
            flash(f"Google Drive connection failed: {result.get('error', 'Unknown error')}", "error")
        return redirect(url_for("settings"))

    @app.route("/settings/google/disconnect", methods=["POST"])
    @login_required
    def gdrive_disconnect():
        from utils import load_settings, save_settings
        google_drive.disconnect()
        settings = load_settings()
        settings["gdrive_user_email"] = ""
        settings["gdrive_last_sync"] = ""
        settings["gdrive_last_sync_status"] = ""
        save_settings(settings)
        flash("Google Drive disconnected.", "success")
        return redirect(url_for("settings"))

    @app.route("/backup/sync", methods=["POST"])
    @login_required
    def gdrive_sync():
        from utils import load_settings, save_settings
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
        name, backup_path = create_backup(db_path, app.config["BACKUP_FOLDER"])
        result = google_drive.upload_backup(backup_path)
        settings = load_settings()
        if result.get("ok"):
            settings["gdrive_last_sync"] = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
            settings["gdrive_last_sync_status"] = "success"
            save_settings(settings)
            flash(f"Synced to Google Drive: {name}", "success")
        else:
            settings["gdrive_last_sync_status"] = f"error: {result.get('error', 'unknown')}"
            save_settings(settings)
            flash(f"Google Drive sync failed: {result.get('error', 'Unknown')}", "error")
        return redirect(url_for("backup"))

    @app.route("/backup/gdrive-list")
    @login_required
    def gdrive_list():
        backups = google_drive.list_backups()
        return jsonify(backups)

    @app.route("/backup/gdrive-restore", methods=["POST"])
    @login_required
    def gdrive_restore():
        file_id = request.form.get("file_id")
        if not file_id:
            flash("No backup selected.", "error")
            return redirect(url_for("backup"))
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
        temp_path = os.path.join(app.config["BACKUP_FOLDER"], "gdrive_restore_temp.bak")
        dl = google_drive.download_backup(file_id, temp_path)
        if dl.get("ok"):
            db.session.remove()
            db.engine.dispose()
            result = restore_backup(temp_path, db_path)
            os.remove(temp_path)
            if result["ok"]:
                flash(f"{result['message']} (Google Drive)", "success")
            else:
                flash(result["message"], "error")
        else:
            flash(f"Restore failed: {dl.get('error', 'Unknown')}", "error")
        return redirect(url_for("backup"))

    @app.route("/backup/sync-status")
    @login_required
    def gdrive_sync_status():
        from utils import load_settings
        settings = load_settings()
        connected = google_drive.is_connected()
        return jsonify({
            "connected": connected,
            "email": settings.get("gdrive_user_email", ""),
            "last_sync": settings.get("gdrive_last_sync", ""),
            "last_status": settings.get("gdrive_last_sync_status", ""),
            "auto_sync": settings.get("gdrive_auto_sync", True),
        })

    def sync_to_gdrive():
        from utils import load_settings
        settings = load_settings()
        if not settings.get("gdrive_auto_sync", True):
            return
        if not google_drive.is_connected():
            return
        try:
            db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
            name, backup_path = create_backup(db_path, app.config["BACKUP_FOLDER"])
            result = google_drive.upload_backup(backup_path)
            settings = load_settings()
            if result.get("ok"):
                settings["gdrive_last_sync"] = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
                settings["gdrive_last_sync_status"] = "success"
            else:
                settings["gdrive_last_sync_status"] = f"error: {result.get('error', '')}"
            save_settings(settings)
        except Exception as e:
            logger.exception("Auto-sync to Google Drive failed")

    @app.after_request
    def auto_gdrive_sync(response):
        if request.method == "POST" and response.status_code < 400:
            gdrive_endpoints = (
                "add_vehicle", "edit_vehicle", "delete_vehicle", "delete_all_vehicles",
                "import_data", "restore",
            )
            if request.endpoint in gdrive_endpoints:
                import threading
                threading.Thread(target=sync_to_gdrive, daemon=True).start()
        return response

    # ---- Settings ------------------------------------------------------------

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        if request.method == "POST":
            from utils import load_settings, save_settings
            current = load_settings()
            panel = request.form.get("panel", "")

            if panel == "provider":
                provider = request.form.get("ai_provider", "openrouter").strip()
                current["ai_provider"] = provider if provider in ("openrouter", "google") else "openrouter"
            elif panel == "openrouter":
                current["openrouter_api_key"] = request.form.get("openrouter_api_key", "").strip()
                model = request.form.get("openrouter_model", "").strip()
                if model:
                    current["openrouter_model"] = model
            elif panel == "google":
                current["google_api_key"] = request.form.get("google_api_key", "").strip()
                google_model = request.form.get("google_model", "").strip()
                if google_model:
                    current["google_model"] = google_model
            elif panel == "gdrive":
                current["gdrive_auto_sync"] = request.form.get("gdrive_auto_sync") == "on"
            elif panel == "email":
                _save_email_form_settings()
                flash("Email settings saved.", "success")
                return redirect(url_for("settings"))
            else:
                provider = request.form.get("ai_provider", "openrouter").strip()
                current["ai_provider"] = provider if provider in ("openrouter", "google") else "openrouter"
                current["openrouter_api_key"] = request.form.get("openrouter_api_key", "").strip()
                current["google_api_key"] = request.form.get("google_api_key", "").strip()
                or_model = request.form.get("openrouter_model", "").strip()
                if or_model:
                    current["openrouter_model"] = or_model
                g_model = request.form.get("google_model", "").strip()
                if g_model:
                    current["google_model"] = g_model
                if "gdrive_auto_sync" in request.form:
                    current["gdrive_auto_sync"] = request.form.get("gdrive_auto_sync") == "on"

            save_settings(current)
            flash("Settings saved successfully.", "success")
            return redirect(url_for("settings"))

        from utils import load_settings
        ai_settings = load_settings()
        ai_settings["gdrive_connected"] = google_drive.is_connected()
        return render_template("settings.html", ai_settings=ai_settings)

    def _save_ai_form_settings(apply_provider=False):
        """Persist AI fields posted from the test forms (only fields present)."""
        from utils import load_settings, save_settings
        current = load_settings()
        if apply_provider:
            provider = request.form.get("ai_provider")
            if provider in ("openrouter", "google"):
                current["ai_provider"] = provider
        api_key = request.form.get("openrouter_api_key")
        if api_key is not None:
            current["openrouter_api_key"] = api_key.strip()
        model = request.form.get("openrouter_model")
        if model:
            current["openrouter_model"] = model.strip()
        google_key = request.form.get("google_api_key")
        if google_key is not None:
            current["google_api_key"] = google_key.strip()
        google_model = request.form.get("google_model")
        if google_model:
            current["google_model"] = google_model.strip()
        save_settings(current)
        return current

    @app.route("/settings/test-api", methods=["POST"])
    @login_required
    def test_api():
        _save_ai_form_settings()
        provider = request.form.get("ai_provider") or None
        result = ai_service.test_api_connection(provider)
        return jsonify(result)

    @app.route("/settings/test-api-debug", methods=["POST"])
    @login_required
    def test_api_debug():
        _save_ai_form_settings()
        provider = request.form.get("ai_provider") or None
        result = ai_service.test_api_connection_debug(provider)
        return jsonify(result)

    def _save_email_form_settings():
        """Persist SMTP email settings posted from the settings/test forms."""
        from utils import load_settings, save_settings
        current = load_settings()
        if "smtp_server" in request.form:
            current["smtp_server"] = request.form.get("smtp_server", "smtp.gmail.com").strip() or "smtp.gmail.com"
            current["smtp_port"] = request.form.get("smtp_port", "587").strip() or "587"
            current["smtp_user"] = request.form.get("smtp_user", "").strip()
            current["smtp_password"] = request.form.get("smtp_password", "").strip()
            current["smtp_from"] = request.form.get("smtp_from", "").strip() or current["smtp_user"]
            current["email_reminders_enabled"] = request.form.get("email_reminders_enabled") == "on"
            current["auto_reminders_enabled"] = request.form.get("auto_reminders_enabled") == "on"
            try:
                windows = sorted({int(w) for w in request.form.getlist("auto_reminder_windows")})
            except (TypeError, ValueError):
                windows = [7, 3, 0]
            current["auto_reminder_windows"] = windows
        save_settings(current)
        return current

    @app.route("/settings/test-email", methods=["POST"])
    @login_required
    def test_email():
        _save_email_form_settings()
        to_email = request.form.get("test_email_to", "").strip()
        if not to_email:
            return jsonify({"ok": False, "error": "No email address provided"})
        result = email_service.send_test_email(to_email)
        return jsonify(result)

    # ---- Tax Details ----------------------------------------------------------

    @app.route("/vehicles/<int:vehicle_id>/tax")
    @login_required
    def vehicle_tax(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        taxes = vehicle.tax_details.order_by(TaxDetail.latest_tax_from.desc()).all()
        return render_template("vehicle_tax.html", vehicle=vehicle, taxes=taxes)

    @app.route("/vehicles/<int:vehicle_id>/tax/add", methods=["GET", "POST"])
    @login_required
    def add_tax(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        if request.method == "POST":
            tax = TaxDetail(
                vehicle_id=vehicle.id,
                tax_mode=request.form.get("tax_mode", "").strip(),
                latest_tax_from=parse_date(request.form.get("latest_tax_from")),
                latest_tax_upto=parse_date(request.form.get("latest_tax_upto")),
                tax_amount=float(request.form.get("tax_amount", 0) or 0),
                penalty=float(request.form.get("penalty", 0) or 0),
            )
            db.session.add(tax)
            db.session.commit()
            flash("Tax detail added successfully.", "success")
            return redirect(url_for("vehicle_tax", vehicle_id=vehicle.id))
        return render_template("tax_form.html", vehicle=vehicle, tax=None)

    @app.route("/tax/<int:tax_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_tax(tax_id):
        tax = TaxDetail.query.get_or_404(tax_id)
        if request.method == "POST":
            tax.tax_mode = request.form.get("tax_mode", "").strip()
            tax.latest_tax_from = parse_date(request.form.get("latest_tax_from"))
            tax.latest_tax_upto = parse_date(request.form.get("latest_tax_upto"))
            tax.tax_amount = float(request.form.get("tax_amount", 0) or 0)
            tax.penalty = float(request.form.get("penalty", 0) or 0)
            db.session.commit()
            flash("Tax detail updated.", "success")
            return redirect(url_for("vehicle_tax", vehicle_id=tax.vehicle_id))
        return render_template("tax_form.html", vehicle=tax.vehicle, tax=tax)

    @app.route("/tax/<int:tax_id>/delete", methods=["POST"])
    @login_required
    def delete_tax(tax_id):
        tax = TaxDetail.query.get_or_404(tax_id)
        vid = tax.vehicle_id
        db.session.delete(tax)
        db.session.commit()
        flash("Tax detail deleted.", "success")
        return redirect(url_for("vehicle_tax", vehicle_id=vid))

    # ---- API used by dashboard charts / AJAX --------------------------------

    @app.route("/api/vehicle/<int:vehicle_id>")
    @login_required
    def api_vehicle(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        return jsonify(vehicle.to_dict())

    @app.route("/api/check-duplicate")
    @login_required
    def check_duplicate():
        field = request.args.get("field", "")
        value = request.args.get("value", "").strip().upper()
        exclude_id = request.args.get("exclude_id", type=int)
        if not field or not value:
            return jsonify({"exists": False})
        query = Vehicle.query.filter(getattr(Vehicle, field) == value)
        if exclude_id:
            query = query.filter(Vehicle.id != exclude_id)
        return jsonify({"exists": query.first() is not None})

    # ---- AI Chat Assistant --------------------------------------------------

    @app.route("/ai/chat", methods=["GET", "POST"])
    @app.route("/ai/chat/<int:session_id>", methods=["GET", "POST"])
    @login_required
    def ai_chat(session_id=None):
        if not ai_service.check_api_key():
            flash("API key not configured. Set it in Settings.", "error")
            return render_template("ai_chat.html", messages=[], ollama_running=False, chat_session=None)

        if request.method == "POST":
            user_msg = request.form.get("message", "").strip()
            if not user_msg:
                flash("Please type a message.", "error")
                return redirect(url_for("ai_chat"))

            sid = request.form.get("session_id")
            if sid:
                chat_session = ChatSession.query.get_or_404(int(sid))
            else:
                chat_session = ChatSession(title=user_msg[:80])
                db.session.add(chat_session)
                db.session.commit()

            user_message = ChatMessage(session_id=chat_session.id, role="user", content=user_msg)
            db.session.add(user_message)
            db.session.commit()

            history = [{"role": m.role, "content": m.content} for m in chat_session.messages.all()]
            vehicles = Vehicle.query.all()
            try:
                ai_reply = ai_service.ask_assistant(user_msg, vehicles, history=history)
            except Exception as exc:
                ai_reply = f"Error communicating with AI: {exc}"

            ai_message = ChatMessage(session_id=chat_session.id, role="assistant", content=ai_reply or "No response.")
            db.session.add(ai_message)
            chat_session.updated_at = datetime.utcnow()
            db.session.commit()

            return redirect(url_for("ai_chat", session_id=chat_session.id))

        chat_session = None
        messages = []
        if session_id:
            chat_session = ChatSession.query.get_or_404(session_id)
            messages = [{"role": m.role, "content": m.content} for m in chat_session.messages.order_by(ChatMessage.id).all()]

        return render_template("ai_chat.html", messages=messages, ollama_running=True, chat_session=chat_session)

    @app.route("/ai/chat/new")
    @login_required
    def ai_chat_new():
        return redirect(url_for("ai_chat"))

    @app.route("/ai/chat/<int:session_id>/delete", methods=["POST"])
    @login_required
    def ai_chat_delete(session_id):
        chat_session = ChatSession.query.get_or_404(session_id)
        db.session.delete(chat_session)
        db.session.commit()
        flash("Chat deleted.", "success")
        return redirect(url_for("ai_chat_history"))

    @app.route("/ai/chat/history")
    @login_required
    def ai_chat_history():
        sessions = ChatSession.query.order_by(ChatSession.updated_at.desc()).all()
        return render_template("ai_chat_history.html", sessions=sessions)

    # ---- AI Document Parser -------------------------------------------------

    @app.route("/ai/parse-document", methods=["GET", "POST"])
    @login_required
    def ai_parse_document():
        if not ai_service.check_api_key():
            flash("AI API key not configured. Set it in Settings.", "error")
            return render_template("ai_document_parser.html", parsed_data=None,
                                   ollama_running=False, recent_scans=recent_document_scans())

        if request.method == "POST":
            file = request.files.get("document")
            if not file or file.filename == "":
                flash("Please upload a document image.", "error")
                return render_template("ai_document_parser.html", parsed_data=None,
                                       ollama_running=True, recent_scans=recent_document_scans())

            try:
                import pytesseract
                from PIL import Image
                import os
                tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                if os.path.exists(tesseract_path):
                    pytesseract.pytesseract.tesseract_cmd = tesseract_path
                img = Image.open(file)
                ocr_text = pytesseract.image_to_string(img)
            except Exception as exc:
                flash(f"OCR failed: {exc}", "error")
                return render_template("ai_document_parser.html", parsed_data=None,
                                       ollama_running=True, recent_scans=recent_document_scans())

            if not ocr_text.strip():
                flash("No text could be extracted from the image.", "error")
                return render_template("ai_document_parser.html", parsed_data=None,
                                       ollama_running=True, recent_scans=recent_document_scans())

            try:
                parsed_data = ai_service.parse_document_text(ocr_text)
            except Exception as exc:
                flash(f"AI parsing failed: {exc}", "error")
                return render_template("ai_document_parser.html", parsed_data=None,
                                       ollama_running=True, recent_scans=recent_document_scans())

            existing_vehicle = find_existing_vehicle(parsed_data) if parsed_data else None
            scan = save_document_scan(file.filename, parsed_data or {}, ocr_text, existing_vehicle)

            return render_template(
                "ai_document_parser.html",
                parsed_data=parsed_data,
                ocr_text=ocr_text,
                ollama_running=True,
                existing_vehicle=existing_vehicle,
                current_scan_id=scan.id,
                recent_scans=recent_document_scans(),
            )

        return render_template("ai_document_parser.html", parsed_data=None, ollama_running=True,
                               existing_vehicle=None, recent_scans=recent_document_scans())

    @app.route("/ai/parse-document/scan/<int:scan_id>")
    @login_required
    def ai_parse_view_scan(scan_id):
        """View a previous scan (read-only)."""
        scan = DocumentScan.query.get_or_404(scan_id)
        parsed_data = scan.data_dict()
        if not parsed_data:
            flash("This scan has no extracted data.", "error")
            return redirect(url_for("ai_parse_document"))
        return render_template(
            "ai_document_parser.html",
            view_scan=scan,
            parsed_data=parsed_data,
            ocr_text=scan.ocr_text,
            ollama_running=True,
            existing_vehicle=find_existing_vehicle(parsed_data),
            recent_scans=recent_document_scans(),
        )

    @app.route("/ai/parse-document/scan/<int:scan_id>/edit")
    @login_required
    def ai_parse_edit_scan(scan_id):
        """Load a previous scan into the editable form."""
        scan = DocumentScan.query.get_or_404(scan_id)
        parsed_data = scan.data_dict()
        if not parsed_data:
            flash("This scan has no extracted data.", "error")
            return redirect(url_for("ai_parse_document"))
        return render_template(
            "ai_document_parser.html",
            edit_scan=scan,
            parsed_data=parsed_data,
            ocr_text=scan.ocr_text,
            ollama_running=True,
            existing_vehicle=find_existing_vehicle(parsed_data),
            current_scan_id=scan.id,
            recent_scans=recent_document_scans(),
        )

    @app.route("/ai/parse-document/add", methods=["POST"])
    @login_required
    def ai_parse_add_vehicle():
        vnum = request.form.get("vehicle_number", "").strip().upper()
        chassis = request.form.get("chassis_number", "").strip().upper()
        scan_id = request.form.get("scan_id", type=int)

        existing = Vehicle.query.filter(
            db.or_(Vehicle.vehicle_number == vnum, Vehicle.chassis_number == chassis)
        ).first()

        if existing:
            updates = {
                "engine_number": request.form.get("engine_number", "").strip().upper(),
                "owner_name": request.form.get("owner_name", "").strip(),
                "mobile_number": request.form.get("mobile_number", "").strip(),
                "vehicle_type": request.form.get("vehicle_type", "").strip(),
                "registration_date": parse_date(request.form.get("registration_date")),
                "puc_expiry": parse_date(request.form.get("puc_expiry")),
                "fitness_expiry": parse_date(request.form.get("fitness_expiry")),
                "permit_expiry": parse_date(request.form.get("permit_expiry")),
                "insurance_expiry": parse_date(request.form.get("insurance_expiry")),
                "insurance_company": request.form.get("insurance_company", "").strip(),
                "policy_number": request.form.get("policy_number", "").strip(),
                "tax_from": parse_date(request.form.get("tax_from")),
                "tax_expiry": parse_date(request.form.get("tax_expiry")),
                "tax_mode": request.form.get("tax_mode", "").strip(),
                "tax_amount": float(request.form.get("tax_amount") or 0),
                "permit_from": parse_date(request.form.get("permit_from")),
                "permit_auth_no": request.form.get("permit_auth_no", "").strip(),
                "permit_address": request.form.get("permit_address", "").strip(),
            }
            updated_fields = []
            for field, value in updates.items():
                if value:
                    old_val = getattr(existing, field)
                    if field.endswith("_date") or field.endswith("_expiry") or field.endswith("_from"):
                        if old_val is None:
                            setattr(existing, field, value)
                            updated_fields.append(field)
                    elif isinstance(value, str) and not value:
                        continue
                    else:
                        if old_val != value:
                            setattr(existing, field, value)
                            updated_fields.append(field)

            existing.updated_at = datetime.utcnow()
            db.session.commit()
            if scan_id:
                scan = DocumentScan.query.get(scan_id)
                if scan:
                    scan.vehicle_id = existing.id
                    db.session.commit()
            flash(f"Vehicle {existing.vehicle_number} updated with {len(updated_fields)} new fields.", "success")
            return redirect(url_for("view_vehicle", vehicle_id=existing.id))

        vehicle = Vehicle(
            vehicle_number=vnum,
            chassis_number=chassis,
            engine_number=request.form.get("engine_number", "").strip().upper(),
            owner_name=request.form.get("owner_name", "").strip(),
            mobile_number=request.form.get("mobile_number", "").strip(),
            vehicle_type=request.form.get("vehicle_type", "").strip(),
            registration_date=parse_date(request.form.get("registration_date")),
            puc_expiry=parse_date(request.form.get("puc_expiry")),
            fitness_expiry=parse_date(request.form.get("fitness_expiry")),
            permit_expiry=parse_date(request.form.get("permit_expiry")),
            insurance_expiry=parse_date(request.form.get("insurance_expiry")),
            insurance_company=request.form.get("insurance_company", "").strip(),
            policy_number=request.form.get("policy_number", "").strip(),
            tax_from=parse_date(request.form.get("tax_from")),
            tax_expiry=parse_date(request.form.get("tax_expiry")),
            tax_mode=request.form.get("tax_mode", "").strip(),
            tax_amount=float(request.form.get("tax_amount") or 0),
            permit_from=parse_date(request.form.get("permit_from")),
            permit_auth_no=request.form.get("permit_auth_no", "").strip(),
            permit_address=request.form.get("permit_address", "").strip(),
        )
        db.session.add(vehicle)
        db.session.commit()
        if scan_id:
            scan = DocumentScan.query.get(scan_id)
            if scan:
                scan.vehicle_id = vehicle.id
                db.session.commit()
        resequence_sr_nos()
        flash(f"Vehicle {vehicle.vehicle_number} added from parsed document.", "success")
        return redirect(url_for("vehicle_list"))

    # ---- AI Insights --------------------------------------------------------

    @app.route("/ai/insights")
    @login_required
    def ai_insights():
        if not ai_service.check_api_key():
            flash("AI API key not configured. Set it in Settings.", "error")
            return render_template("ai_insights.html", insights=None, ollama_running=False)

        vehicles = Vehicle.query.all()
        try:
            insights = ai_service.generate_insights(vehicles)
        except Exception as exc:
            flash(f"Failed to generate insights: {exc}", "error")
            return render_template("ai_insights.html", insights=None, ollama_running=True)

        return render_template("ai_insights.html", insights=insights, ollama_running=True)


def update_vehicle_from_record(vehicle, record):
    """Update an existing vehicle from an imported record dict."""
    if "engine_number" in record:
        vehicle.engine_number = str(record.get("engine_number", "") or vehicle.engine_number or "").strip().upper()
    if "owner_name" in record:
        vehicle.owner_name = str(record.get("owner_name", "") or vehicle.owner_name or "").strip()
    if "owner_email" in record:
        vehicle.owner_email = email_service.normalize_emails(str(record.get("owner_email", "") or vehicle.owner_email or ""))
    if "mobile_number" in record:
        vehicle.mobile_number = str(record.get("mobile_number", "") or vehicle.mobile_number or "").strip()
    if "vehicle_type" in record:
        vehicle.vehicle_type = str(record.get("vehicle_type", "") or vehicle.vehicle_type or "").strip()
    if "district" in record:
        vehicle.district = str(record.get("district", "") or vehicle.district or "").strip()
    if "registration_date" in record:
        parsed = parse_date(record.get("registration_date"))
        if parsed:
            vehicle.registration_date = parsed
    if "puc_expiry" in record:
        parsed = parse_date(record.get("puc_expiry"))
        if parsed:
            vehicle.puc_expiry = parsed
    if "fitness_expiry" in record:
        parsed = parse_date(record.get("fitness_expiry"))
        if parsed:
            vehicle.fitness_expiry = parsed
    if "permit_expiry" in record:
        parsed = parse_date(record.get("permit_expiry"))
        if parsed:
            vehicle.permit_expiry = parsed
    if "tax_from" in record:
        parsed = parse_date(record.get("tax_from"))
        if parsed:
            vehicle.tax_from = parsed
    if "tax_expiry" in record:
        parsed = parse_date(record.get("tax_expiry"))
        if parsed:
            vehicle.tax_expiry = parsed
    if "tax_mode" in record:
        vehicle.tax_mode = str(record.get("tax_mode", "") or vehicle.tax_mode or "").strip()
    if "tax_amount" in record:
        val = record.get("tax_amount")
        if val is not None:
            vehicle.tax_amount = float(val or 0)
    if "insurance_expiry" in record:
        parsed = parse_date(record.get("insurance_expiry"))
        if parsed:
            vehicle.insurance_expiry = parsed
    if "national_permit_expiry" in record:
        parsed = parse_date(record.get("national_permit_expiry"))
        if parsed:
            vehicle.national_permit_expiry = parsed
    if "state_permit_expiry" in record:
        parsed = parse_date(record.get("state_permit_expiry"))
        if parsed:
            vehicle.state_permit_expiry = parsed
    if "pollution_certificate_number" in record:
        vehicle.pollution_certificate_number = str(record.get("pollution_certificate_number", "") or vehicle.pollution_certificate_number or "").strip()
    if "insurance_company" in record:
        vehicle.insurance_company = str(record.get("insurance_company", "") or vehicle.insurance_company or "").strip()
    if "policy_number" in record:
        vehicle.policy_number = str(record.get("policy_number", "") or vehicle.policy_number or "").strip()
    if "remarks" in record:
        vehicle.remarks = str(record.get("remarks", "") or vehicle.remarks or "").strip()
    vehicle.updated_at = datetime.utcnow()


def validate_vehicle_form(form, editing_id=None):
    errors = []
    vehicle_number = form.get("vehicle_number", "").strip()
    chassis_number = form.get("chassis_number", "").strip()
    mobile_number = form.get("mobile_number", "").strip()
    owner_name = form.get("owner_name", "").strip()

    if not vehicle_number:
        errors.append("Vehicle Number is required.")
    if not chassis_number:
        errors.append("Chassis Number is required.")
    if not owner_name:
        errors.append("Owner Name is required.")
    if mobile_number and not mobile_number.replace("+", "").isdigit():
        errors.append("Mobile Number should be numeric.")
    owner_email = form.get("owner_email", "").strip()
    if owner_email:
        ok, err = email_service.validate_emails(owner_email)
        if not ok:
            errors.append(err)

    if vehicle_number:
        query = Vehicle.query.filter(Vehicle.vehicle_number == vehicle_number.upper())
        if editing_id:
            query = query.filter(Vehicle.id != editing_id)
        if query.first():
            errors.append(f"Vehicle Number {vehicle_number} already exists.")

    if chassis_number:
        query = Vehicle.query.filter(Vehicle.chassis_number == chassis_number.upper())
        if editing_id:
            query = query.filter(Vehicle.id != editing_id)
        if query.first():
            errors.append(f"Chassis Number {chassis_number} already exists.")

    return errors


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
