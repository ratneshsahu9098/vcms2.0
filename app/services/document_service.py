"""Document scan persistence helpers (AI document parser)."""
import json

from app.extensions import db
from app.models import DocumentScan, Vehicle


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


COMPARISON_FIELDS = [
    ("engine_number", "Engine Number"),
    ("owner_name", "Owner Name"),
    ("owner_email", "Owner Email"),
    ("mobile_number", "Mobile Number"),
    ("vehicle_type", "Vehicle Type"),
    ("registration_date", "Registration Date"),
    ("puc_expiry", "PUC Expiry"),
    ("fitness_expiry", "Fitness Expiry"),
    ("permit_from", "Permit From"),
    ("permit_expiry", "Permit Expiry"),
    ("permit_auth_no", "Permit Auth No."),
    ("permit_address", "Permit Address"),
    ("tax_from", "Tax Period From"),
    ("tax_expiry", "Tax Valid Until"),
    ("tax_mode", "Tax Mode"),
    ("tax_amount", "Tax Amount"),
    ("insurance_expiry", "Insurance Expiry"),
    ("insurance_company", "Insurance Company"),
    ("policy_number", "Policy Number"),
]


def _norm(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _is_empty(value):
    return _norm(value) in ("", "0")


def build_comparison(existing, parsed_data):
    """Diff scanned fields against an existing vehicle for the review table.

    Rows with an empty/zero scanned value are skipped (nothing to fill).
    Status: empty -> auto-fill, changed -> needs acceptance, same -> no-op.
    """
    rows = []
    for field, label in COMPARISON_FIELDS:
        scanned = parsed_data.get(field)
        if _is_empty(scanned):
            continue
        current = getattr(existing, field, None)
        if _is_empty(current):
            status = "empty"
        elif _norm(current) == _norm(scanned):
            status = "same"
        else:
            status = "changed"
        rows.append({
            "field": field,
            "label": label,
            "existing_value": _norm(current) or "—",
            "scanned_value": _norm(scanned),
            "status": status,
        })
    return rows


def prune_document_scans(keep=20):
    stale = DocumentScan.query.order_by(
        DocumentScan.scanned_at.desc(), DocumentScan.id.desc()
    ).offset(keep).all()
    for s in stale:
        db.session.delete(s)
    if stale:
        db.session.commit()

