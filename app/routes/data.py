"""Excel/CSV import and export wizard."""
import csv
from datetime import date, datetime
import io
import json
import os
import re
import secrets
import time
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
from app.utils.files import IMPORT_COLUMN_MAP

bp = Blueprint("data", __name__)

# ---- Excel Import --------------------------------------------------------

IMPORT_TEMPLATE_HEADERS = [
    "Vehicle Number", "Chassis Number", "Engine Number", "Owner Name",
    "Owner Email", "Phone", "Vehicle Type", "District", "Registration Date",
    "PUC Expiry", "Fitness Expiry", "Permit From", "Permit Expiry",
    "Tax From", "Tax Expiry", "Tax Mode", "Tax Amount",
    "Insurance Expiry", "National Permit Expiry", "State Permit Expiry",
    "Pollution Certificate Number", "Insurance Company", "Policy Number",
    "Remarks",
]

IMPORT_TEMPLATE_ROW = [
    "MH01AB1234", "MA1XXXXXXXXX1", "KXXXX12345", "Ramesh Kumar",
    "ramesh@example.com", "9876543210", "Truck", "Indore", "2024-01-15",
    "2026-05-30", "2026-08-12", "2025-12-01", "2026-11-30",
    "2025-04-01", "2025-12-31", "Quarterly (Q)", "3500",
    "2026-02-20", "2026-06-30", "2026-09-30",
    "PUC-123456", "ICICI Lombard", "POL-998877",
    "Sample row - delete before importing",
]

IMPORT_REQUIRED_FIELDS = ("vehicle_number", "chassis_number", "owner_name", "mobile_number")

_IMPORT_FIELDS = frozenset({
    "engine_number", "owner_name", "mobile_number", "owner_email", "vehicle_type",
    "district", "registration_date", "puc_expiry", "fitness_expiry", "permit_expiry",
    "permit_from", "tax_from", "tax_expiry", "tax_mode", "tax_amount",
    "insurance_expiry", "national_permit_expiry", "state_permit_expiry",
    "pollution_certificate_number", "insurance_company", "policy_number", "remarks",
})

_PREVIEW_LIMIT = 100
_RESULT_ERROR_LIMIT = 50
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _sample_template():
    """CSV template with every supported header and one example row."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(IMPORT_TEMPLATE_HEADERS)
    writer.writerow(IMPORT_TEMPLATE_ROW)
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="vehicle_import_template.csv",
    )


def _cache_path(token):
    """Safe path for an import preview cache file, or None if the token is invalid."""
    if not token or not _TOKEN_RE.match(token):
        return None
    return os.path.join(Config.IMPORT_CACHE_DIR, token + ".json")


def _purge_cache(max_age=3600):
    """Remove preview cache files older than max_age seconds."""
    try:
        for name in os.listdir(Config.IMPORT_CACHE_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(Config.IMPORT_CACHE_DIR, name)
            if time.time() - os.path.getmtime(path) > max_age:
                os.remove(path)
    except OSError:
        pass


def _json_safe(value):
    """Normalize a cell value to a JSON-safe primitive (dates -> ISO strings)."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    return value


def _read_upload(file):
    """Parse an uploaded file into rows of records.

    Returns (rows, columns); each row is {"row": <source row>, "data": {field: value}}.
    Raises ValueError with a user-friendly message.
    """
    if file is None or not file.filename:
        raise ValueError("Please choose a file to import.")
    if not allowed_file(file.filename, Config.ALLOWED_IMPORT_EXTENSIONS):
        raise ValueError("Unsupported file type. Please upload .xlsx, .xls, .csv, or .json")
    payload = file.read()
    if not payload:
        raise ValueError("The file is empty.")
    if len(payload) > Config.IMPORT_MAX_MB * 1024 * 1024:
        raise ValueError(f"File is too large. Maximum size is {Config.IMPORT_MAX_MB} MB.")
    name = file.filename.lower()

    if name.endswith(".json"):
        try:
            raw = json.loads(payload.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"Could not read file: {exc}")
        if not isinstance(raw, list) or not raw:
            raise ValueError("JSON file must contain a non-empty array of vehicle objects.")
        if not all(isinstance(rec, dict) for rec in raw):
            raise ValueError("JSON array must contain only objects.")
        columns = []
        for rec in raw:
            for key in rec:
                if key not in columns:
                    columns.append(key)
        return [{"row": i + 1, "data": rec} for i, rec in enumerate(raw)], columns

    try:
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
        else:
            df = pd.read_excel(io.BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"Could not read file: {exc}")

    df = normalize_import_dataframe(df)
    missing = set(IMPORT_REQUIRED_FIELDS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    if df.empty:
        raise ValueError("The file has no data rows.")
    rows = [
        {"row": i + 2, "data": {k: _json_safe(v) for k, v in rec.items()}}
        for i, rec in enumerate(df.to_dict(orient="records"))
    ]
    return rows, [str(c) for c in df.columns]


def _plan_import(rows, duplicate_action):
    """Classify each row read-only: add / update / skip / error."""
    plan = []
    seen = {}
    for item in rows:
        data = item["data"]
        row_no = item["row"]
        vnum = str(data.get("vehicle_number") or "").strip().upper()
        chassis = str(data.get("chassis_number") or "").strip().upper()
        if not vnum or not chassis or vnum.lower() == "nan" or chassis.lower() == "nan":
            plan.append({"row": row_no, "data": data, "action": "error",
                         "reason": "Missing vehicle or chassis number", "existing": None})
            continue
        dup_row = seen.get(vnum) or seen.get(chassis)
        if dup_row:
            plan.append({"row": row_no, "data": data, "action": "skip",
                         "reason": f"Duplicate of row {dup_row} in this file",
                         "existing": None})
            continue
        seen[vnum] = row_no
        seen[chassis] = row_no
        existing = Vehicle.query.filter(
            db.or_(Vehicle.vehicle_number == vnum, Vehicle.chassis_number == chassis)
        ).first()
        if existing is None:
            plan.append({"row": row_no, "data": data, "action": "add",
                         "reason": "", "existing": None})
        elif duplicate_action == "update":
            plan.append({"row": row_no, "data": data, "action": "update",
                         "reason": f"Matches existing {existing.vehicle_number}",
                         "existing": existing})
        else:
            plan.append({"row": row_no, "data": data, "action": "skip",
                         "reason": f"Duplicate of {existing.vehicle_number}",
                         "existing": None})
    return plan


def _plan_stats(plan):
    stats = {"total": len(plan), "add": 0, "update": 0, "skip": 0, "error": 0}
    for entry in plan:
        stats[entry["action"]] += 1
    return stats


def _vehicle_from_data(data):
    def text(key, upper=False):
        value = str(data.get(key) or "").strip()
        return value.upper() if upper else value

    return Vehicle(
        vehicle_number=text("vehicle_number", upper=True),
        chassis_number=text("chassis_number", upper=True),
        engine_number=text("engine_number", upper=True),
        owner_name=text("owner_name"),
        mobile_number=text("mobile_number"),
        owner_email=email_service.normalize_emails(text("owner_email")),
        vehicle_type=text("vehicle_type"),
        district=text("district"),
        registration_date=parse_date(data.get("registration_date")),
        puc_expiry=parse_date(data.get("puc_expiry")),
        fitness_expiry=parse_date(data.get("fitness_expiry")),
        permit_from=parse_date(data.get("permit_from")),
        permit_expiry=parse_date(data.get("permit_expiry")),
        tax_from=parse_date(data.get("tax_from")),
        tax_expiry=parse_date(data.get("tax_expiry")),
        tax_mode=text("tax_mode"),
        tax_amount=to_float(data.get("tax_amount")),
        insurance_expiry=parse_date(data.get("insurance_expiry")),
        national_permit_expiry=parse_date(data.get("national_permit_expiry")),
        state_permit_expiry=parse_date(data.get("state_permit_expiry")),
        pollution_certificate_number=text("pollution_certificate_number"),
        insurance_company=text("insurance_company"),
        policy_number=text("policy_number"),
        remarks=text("remarks"),
    )


def _execute_plan(plan):
    """Apply a plan to the database. Returns (imported, updated, skipped, errors)."""
    imported = updated = skipped = 0
    errors = []
    for entry in plan:
        if entry["action"] == "add":
            db.session.add(_vehicle_from_data(entry["data"]))
            imported += 1
        elif entry["action"] == "update":
            update_vehicle_from_record(entry["existing"], entry["data"])
            updated += 1
        else:
            skipped += 1
            if entry["reason"]:
                errors.append({"row": entry["row"], "reason": entry["reason"]})
    db.session.commit()
    resequence_sr_nos()
    return imported, updated, skipped, errors


def _commit_preview():
    """Execute a cached preview: plan fresh against current data, then save."""
    path = _cache_path(request.form.get("token", ""))
    if path is None or not os.path.isfile(path):
        flash("Import session expired. Please upload the file again.", "error")
        return redirect(url_for("data.import_excel"))
    try:
        with open(path, encoding="utf-8") as fh:
            cached = json.load(fh)
        rows = cached.get("rows") or []
        duplicate_action = cached.get("duplicate_action", "skip")
        plan = _plan_import(rows, duplicate_action)
        imported, updated, skipped, errors = _execute_plan(plan)
    except Exception as exc:
        db.session.rollback()
        flash(f"Import failed: {exc}", "error")
        return redirect(url_for("data.import_excel"))
    try:
        os.remove(path)
    except OSError:
        pass
    session["import_result"] = {
        "filename": cached.get("filename", ""),
        "duplicate_action": duplicate_action,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:_RESULT_ERROR_LIMIT],
        "error_total": len(errors),
    }
    return redirect(url_for("data.import_excel"))


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_excel():
    if request.args.get("download") == "template":
        return _sample_template()

    if request.method == "POST":
        if request.form.get("phase") == "commit":
            return _commit_preview()

        upload = request.files.get("file")
        try:
            rows, columns = _read_upload(upload)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("data.import_excel"))

        duplicate_action = "update" if request.form.get("duplicate_action") == "update" else "skip"
        plan = _plan_import(rows, duplicate_action)
        token = secrets.token_urlsafe(16)
        os.makedirs(Config.IMPORT_CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(Config.IMPORT_CACHE_DIR, token + ".json")
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump({
                "created": time.time(),
                "filename": upload.filename,
                "duplicate_action": duplicate_action,
                "rows": rows,
            }, fh, default=str)
        _purge_cache()

        column_map = []
        for col in columns:
            key = str(col).strip().lower()
            if key in IMPORT_COLUMN_MAP:
                column_map.append((str(col), IMPORT_COLUMN_MAP[key]))
            elif str(col) in _IMPORT_FIELDS:
                column_map.append((str(col), str(col)))
            else:
                column_map.append((str(col), None))

        return render_template(
            "import_excel.html",
            step=1,
            token=token,
            filename=upload.filename,
            duplicate_action=duplicate_action,
            plan=plan,
            stats=_plan_stats(plan),
            column_map=column_map,
            preview_limit=_PREVIEW_LIMIT,
        )

    cancel_path = _cache_path(request.args.get("cancel", ""))
    if cancel_path and os.path.isfile(cancel_path):
        try:
            os.remove(cancel_path)
        except OSError:
            pass
    _purge_cache()
    result = session.pop("import_result", None)
    return render_template("import_excel.html", step=2 if result else 0, result=result)

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


