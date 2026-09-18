import hashlib
import json
import os
import shutil
from datetime import datetime, date

import pandas as pd


DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]


def parse_date(value):
    """Parse a date from a string, Excel/pandas value, or date/datetime object."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def allowed_file(filename, allowed_extensions):
    return filename and "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


IMPORT_COLUMN_MAP = {
    "vehicle number": "vehicle_number",
    "chassis number": "chassis_number",
    "engine number": "engine_number",
    "owner name": "owner_name",
    "owner email": "owner_email",
    "email": "owner_email",
    "phone": "mobile_number",
    "mobile number": "mobile_number",
    "vehicle type": "vehicle_type",
    "district": "district",
    "registration date": "registration_date",
    "puc": "puc_expiry",
    "puc expiry": "puc_expiry",
    "fitness": "fitness_expiry",
    "fitness expiry": "fitness_expiry",
    "permit": "permit_expiry",
    "permit expiry": "permit_expiry",
    "tax": "tax_expiry",
    "tax expiry": "tax_expiry",
    "tax from": "tax_from",
    "tax mode": "tax_mode",
    "tax amount": "tax_amount",
    "insurance": "insurance_expiry",
    "insurance expiry": "insurance_expiry",
    "national permit": "national_permit_expiry",
    "national permit expiry": "national_permit_expiry",
    "np auth no": "national_permit_number",
    "np auth": "national_permit_number",
    "national permit number": "national_permit_number",
    "national permit auth": "national_permit_number",
    "state permit": "state_permit_expiry",
    "state permit expiry": "state_permit_expiry",
    "address": "address",
    "owner address": "address",
    "registered address": "address",
    "pollution certificate number": "pollution_certificate_number",
    "pollution cert no": "pollution_certificate_number",
    "insurance company": "insurance_company",
    "policy number": "policy_number",
    "remarks": "remarks",
}


def normalize_import_dataframe(df):
    """Rename columns from the Excel import template to internal field names."""
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in IMPORT_COLUMN_MAP:
            rename[col] = IMPORT_COLUMN_MAP[key]
    return df.rename(columns=rename)


def _file_md5(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_last_backup_meta(subfolder_path):
    meta_file = os.path.join(subfolder_path, ".last_backup.json")
    if os.path.exists(meta_file):
        with open(meta_file, "r") as f:
            return json.load(f)
    return None


def _save_last_backup_meta(subfolder_path, md5, backup_name):
    meta_file = os.path.join(subfolder_path, ".last_backup.json")
    with open(meta_file, "w") as f:
        json.dump({"md5": md5, "backup_name": backup_name, "timestamp": datetime.now().isoformat()}, f)


def _is_backup_duplicate(subfolder_path, current_md5):
    last_meta = _load_last_backup_meta(subfolder_path)
    if not last_meta:
        return False, None

    if last_meta.get("md5") == current_md5:
        last_ts = last_meta.get("timestamp", "")
        if last_ts:
            try:
                last_time = datetime.fromisoformat(last_ts)
                elapsed = (datetime.now() - last_time).total_seconds()
                if elapsed < 30:
                    return True, last_meta.get("backup_name")
            except (ValueError, TypeError):
                pass
        return True, last_meta.get("backup_name")

    return False, None


def create_backup(db_path, backup_folder, subfolder="local"):
    lock_file = os.path.join(backup_folder, f".{subfolder}.backup.lock")

    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                lock_ts = float(f.read().strip())
            if (datetime.now().timestamp() - lock_ts) < 10:
                meta = _load_last_backup_meta(os.path.join(backup_folder, subfolder))
                if meta:
                    today = datetime.now().strftime("%Y-%m-%d")
                    existing_path = os.path.join(backup_folder, subfolder, today, meta["backup_name"])
                    if os.path.exists(existing_path):
                        return meta["backup_name"], existing_path
        except (ValueError, IOError):
            pass

    with open(lock_file, "w") as f:
        f.write(str(datetime.now().timestamp()))

    try:
        current_md5 = _file_md5(db_path)
        subfolder_path = os.path.join(backup_folder, subfolder)
        os.makedirs(subfolder_path, exist_ok=True)

        is_dup, existing_name = _is_backup_duplicate(subfolder_path, current_md5)
        if is_dup and existing_name:
            today = datetime.now().strftime("%Y-%m-%d")
            existing_path = os.path.join(subfolder_path, today, existing_name)
            if os.path.exists(existing_path):
                return existing_name, existing_path

        today = datetime.now().strftime("%Y-%m-%d")
        target_dir = os.path.join(backup_folder, subfolder, today)
        os.makedirs(target_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S")
        backup_name = f"backup_{timestamp}.db"
        backup_path = os.path.join(target_dir, backup_name)
        shutil.copy2(db_path, backup_path)

        _save_last_backup_meta(subfolder_path, current_md5, backup_name)

        return backup_name, backup_path
    finally:
        if os.path.exists(lock_file):
            os.remove(lock_file)


def list_backups(backup_folder, subfolder="local"):
    subfolder_path = os.path.join(backup_folder, subfolder)
    if not os.path.isdir(subfolder_path):
        return []
    backups = []
    for date_dir in sorted(os.listdir(subfolder_path), reverse=True):
        date_path = os.path.join(subfolder_path, date_dir)
        if not os.path.isdir(date_path):
            continue
        for f in os.listdir(date_path):
            if not f.endswith(".db"):
                continue
            path = os.path.join(date_path, f)
            stat = os.stat(path)
            size = stat.st_size
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            created = datetime.fromtimestamp(stat.st_mtime)
            backups.append({
                "name": f,
                "date": date_dir,
                "path": path,
                "rel_path": os.path.join(subfolder, date_dir, f),
                "created": created.strftime("%d %b %Y, %I:%M %p"),
                "size": size_str,
            })
    backups.sort(key=lambda x: x["rel_path"], reverse=True)
    return backups


def whatsapp_message(vehicle, document_label, expiry_date):
    lines = [
        f"Vehicle Compliance Details",
        f"{'=' * 30}",
        f"",
        f"Vehicle No: {vehicle.vehicle_number}",
        f"Chassis No: {vehicle.chassis_number}",
        f"Engine No: {vehicle.engine_number or 'N/A'}",
        f"Owner: {vehicle.owner_name}",
        f"Mobile: {vehicle.mobile_number}",
        f"Type: {vehicle.vehicle_type or 'N/A'}",
        f"District: {vehicle.district or 'N/A'}",
        f"Registration: {vehicle.registration_date.strftime('%d-%m-%Y') if vehicle.registration_date else 'N/A'}",
        f"",
        f"--- Document Status ---",
        f"PUC Expiry: {vehicle.puc_expiry.strftime('%d-%m-%Y') if vehicle.puc_expiry else 'Not Set'}",
        f"Fitness Expiry: {vehicle.fitness_expiry.strftime('%d-%m-%Y') if vehicle.fitness_expiry else 'Not Set'}",
        f"Permit Expiry: {vehicle.permit_expiry.strftime('%d-%m-%Y') if vehicle.permit_expiry else 'Not Set'}",
        f"Tax Expiry: {vehicle.tax_expiry.strftime('%d-%m-%Y') if vehicle.tax_expiry else 'Not Set'}",
        f"Tax Mode: {vehicle.tax_mode or 'N/A'}",
        f"Tax Amount: {('₹%.2f' % vehicle.tax_amount) if vehicle.tax_amount else 'N/A'}",
        f"Insurance Expiry: {vehicle.insurance_expiry.strftime('%d-%m-%Y') if vehicle.insurance_expiry else 'Not Set'}",
        f"National Permit: {vehicle.national_permit_expiry.strftime('%d-%m-%Y') if vehicle.national_permit_expiry else 'Not Set'}",
        f"State Permit: {vehicle.state_permit_expiry.strftime('%d-%m-%Y') if vehicle.state_permit_expiry else 'Not Set'}",
        f"",
        f"Insurance Co: {vehicle.insurance_company or 'N/A'}",
        f"Policy No: {vehicle.policy_number or 'N/A'}",
        f"Pollution Cert: {vehicle.pollution_certificate_number or 'N/A'}",
        f"",
    ]
    if document_label and expiry_date:
        lines.append(f"*** {document_label} expires on {expiry_date.strftime('%d %B %Y')} - Please renew! ***")
    if vehicle.remarks:
        lines.append(f"Remarks: {vehicle.remarks}")
    return "\n".join(lines)


def whatsapp_expired_reminder(vehicle):
    """Generate a WhatsApp message with only expired/expiring document details."""
    today = date.today()
    statuses = vehicle.document_statuses()

    expired_docs = []
    for label, info in statuses.items():
        expiry = info["expiry"]
        if expiry is None:
            continue
        days_left = (expiry - today).days
        if days_left <= 30:
            expired_docs.append((label, expiry, days_left))

    if not expired_docs:
        return None

    lines = [
        f"VEHICLE EXPIRY ALERT",
        f"{'=' * 30}",
        f"",
        f"Vehicle No : {vehicle.vehicle_number}",
        f"Chassis No : {vehicle.chassis_number}",
        f"Owner      : {vehicle.owner_name}",
        f"Mobile     : {vehicle.mobile_number}",
        f"Type       : {vehicle.vehicle_type or 'N/A'}",
        f"District   : {vehicle.district or 'N/A'}",
        f"",
        f"--- Expired / Expiring Documents ---",
        f"",
    ]

    for label, expiry, days_left in expired_docs:
        date_str = expiry.strftime('%d-%m-%Y')
        if days_left < 0:
            lines.append(f"{label} : Expired on {date_str} ({abs(days_left)} days ago)")
        elif days_left == 0:
            lines.append(f"{label} : Expires today ({date_str})")
        else:
            lines.append(f"{label} : Expires on {date_str} ({days_left} days left)")

    lines.append(f"")
    lines.append(f"Please renew immediately to avoid penalties.")

    return "\n".join(lines)


def generate_vehicle_qr(vehicle):
    """Generate a QR code image with structured offline vehicle data."""
    import qrcode
    from io import BytesIO

    def fmt_date(d):
        return d.strftime("%d-%m-%Y") if d else "Not Set"

    report_id = f"VC-{vehicle.created_at.strftime('%Y%m%d')}-{vehicle.id:04d}" if vehicle.created_at else f"VC-{vehicle.id:04d}"

    qr_text = (
        f"VCMS - VEHICLE COMPLIANCE\n"
        f"{'=' * 32}\n"
        f"\n"
        f"Vehicle No  : {vehicle.vehicle_number}\n"
        f"Vehicle ID  : {vehicle.id}\n"
        f"Report ID   : {report_id}\n"
        f"\n"
        f"Owner       : {vehicle.owner_name}\n"
        f"Mobile      : {vehicle.mobile_number or 'N/A'}\n"
        f"\n"
        f"Type        : {vehicle.vehicle_type or 'N/A'}\n"
        f"District    : {vehicle.district or 'N/A'}\n"
        f"Registration: {fmt_date(vehicle.registration_date)}\n"
        f"\n"
        f"Chassis     : {vehicle.chassis_number}\n"
        f"Engine      : {vehicle.engine_number or 'N/A'}\n"
        f"\n"
        f"{'-' * 32}\n"
        f"DOCUMENT STATUS\n"
        f"{'-' * 32}\n"
        f"\n"
        f"PUC         : {fmt_date(vehicle.puc_expiry)}\n"
        f"Fitness     : {fmt_date(vehicle.fitness_expiry)}\n"
        f"Permit      : {fmt_date(vehicle.permit_expiry)}\n"
        f"Tax         : {fmt_date(vehicle.tax_expiry)}\n"
        f"Tax Mode    : {vehicle.tax_mode or 'N/A'}\n"
        f"Tax Amount  : {'₹%.2f' % vehicle.tax_amount if vehicle.tax_amount else 'N/A'}\n"
        f"Insurance   : {fmt_date(vehicle.insurance_expiry)}\n"
        f"Nat Permit  : {fmt_date(vehicle.national_permit_expiry)}\n"
        f"State Permit: {fmt_date(vehicle.state_permit_expiry)}\n"
        f"\n"
        f"Insurance Co: {vehicle.insurance_company or 'N/A'}\n"
        f"Policy No   : {vehicle.policy_number or 'N/A'}\n"
        f"Pollution   : {vehicle.pollution_certificate_number or 'N/A'}\n"
        f"\n"
    )
    if vehicle.remarks:
        qr_text += f"Remarks     : {vehicle.remarks}\n"
        qr_text += f"\n"
    qr_text += f"Generated by VCMS\n"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

DEFAULT_SETTINGS = {
    "openrouter_api_key": "",
    "openrouter_model": "dots-studio/dots-3-note-preview:free",
    "gdrive_auto_sync": True,
    "gdrive_last_sync": "",
    "gdrive_last_sync_status": "",
    "gdrive_user_email": "",
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            saved = json.load(f)
            settings = dict(DEFAULT_SETTINGS)
            settings.update(saved)
    else:
        settings = dict(DEFAULT_SETTINGS)

    env_key = os.environ.get("VCMS_OPENROUTER_KEY", "")
    if env_key and not settings.get("openrouter_api_key"):
        settings["openrouter_api_key"] = env_key

    env_model = os.environ.get("VCMS_OPENROUTER_MODEL", "")
    if env_model and not settings.get("openrouter_model"):
        settings["openrouter_model"] = env_model

    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
