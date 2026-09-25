"""Vehicle business logic: form validation and record mapping."""
from datetime import datetime

from app.models import Vehicle
from app.services import email_service
from app.utils import parse_date


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
