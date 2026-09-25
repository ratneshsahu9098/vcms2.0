IMPORT_COLUMN_MAP = {
    "vehicle number": "vehicle_number",
    "chassis number": "chassis_number",
    "engine number": "engine_number",
    "owner name": "owner_name",
    "owner email": "owner_email",
    "email": "owner_email",
    "email address": "owner_email",
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
    "permit from": "permit_from",
    "tax": "tax_expiry",
    "tax expiry": "tax_expiry",
    "tax from": "tax_from",
    "tax mode": "tax_mode",
    "tax amount": "tax_amount",
    "insurance": "insurance_expiry",
    "insurance expiry": "insurance_expiry",
    "national permit": "national_permit_expiry",
    "national permit expiry": "national_permit_expiry",
    "state permit": "state_permit_expiry",
    "state permit expiry": "state_permit_expiry",
    "pollution certificate number": "pollution_certificate_number",
    "pollution cert no": "pollution_certificate_number",
    "insurance company": "insurance_company",
    "policy number": "policy_number",
    "remarks": "remarks",
}


def allowed_file(filename, allowed_extensions):
    return filename and "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def normalize_import_dataframe(df):
    """Rename columns from the Excel import template to internal field names."""
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in IMPORT_COLUMN_MAP:
            rename[col] = IMPORT_COLUMN_MAP[key]
    return df.rename(columns=rename)
