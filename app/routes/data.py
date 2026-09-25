"""Excel/CSV import and export wizard."""
from datetime import date, datetime
import io
import json
from types import SimpleNamespace

import pandas as pd
from flask import (Blueprint, flash, redirect, render_template, request, send_file, session, url_for)

from app.config import Config
from app.constants import EXPORT_COLUMNS
from app.extensions import db
from app.middleware import login_required
from app.migrations import resequence_sr_nos
from app.models import (Vehicle)
from app.services import email_service
from app.services.vehicle_service import (update_vehicle_from_record)
from app.utils import (allowed_file, normalize_import_dataframe, parse_date, to_float)

bp = Blueprint("data", __name__)

# ---- Excel Import --------------------------------------------------------

@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_excel():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose a file to import.", "error")
            return redirect(url_for("data.import_excel"))

        if not allowed_file(file.filename, Config.ALLOWED_IMPORT_EXTENSIONS):
            flash("Unsupported file type. Please upload .xlsx, .xls, .csv, or .json", "error")
            return redirect(url_for("data.import_excel"))

        try:
            if file.filename.lower().endswith(".json"):
                raw = json.load(file)
            elif file.filename.lower().endswith(".csv"):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
        except Exception as exc:
            flash(f"Could not read file: {exc}", "error")
            return redirect(url_for("data.import_excel"))

        duplicate_action = request.form.get("duplicate_action", "skip")
        imported, updated, skipped, errors = 0, 0, 0, []

        if file.filename.lower().endswith(".json"):
            if not isinstance(raw, list):
                flash("JSON file must contain an array of vehicle objects.", "error")
                return redirect(url_for("data.import_excel"))
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
                    tax_amount=to_float(record.get("tax_amount")),
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
                return redirect(url_for("data.import_excel"))

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
                    tax_amount=to_float(row.get("tax_amount")),
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
        return redirect(url_for("data.import_excel"))

    import_errors = session.pop("import_errors", [])
    return render_template("import_excel.html", import_errors=import_errors)

# ---- Excel Export --------------------------------------------------------

@bp.route("/export")
@login_required
def export_excel():
    owners = [r[0] for r in db.session.query(Vehicle.owner_name).distinct().order_by(Vehicle.owner_name) if r[0]]
    vehicles = Vehicle.query.all()
    today = date.today()
    scope_counts = SimpleNamespace(
        all=len(vehicles),
        expired=sum(1 for v in vehicles if v.overall_status() == "status-red"),
        due7=sum(1 for v in vehicles if any(
            info["expiry"] and 0 <= (info["expiry"] - today).days <= 7
            for info in v.document_statuses().values())),
        due30=sum(1 for v in vehicles if any(
            info["expiry"] and 0 <= (info["expiry"] - today).days <= 30
            for info in v.document_statuses().values())),
    )
    return render_template(
        "export_excel.html", export_columns=EXPORT_COLUMNS, owners=owners,
        total_vehicles=len(vehicles), scope_counts=scope_counts,
    )

@bp.route("/export/run")
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


