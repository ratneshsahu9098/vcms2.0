from datetime import date


def whatsapp_message(vehicle, document_label, expiry_date):
    lines = [
        "Vehicle Compliance Details",
        f"{'=' * 30}",
        "",
        f"Vehicle No: {vehicle.vehicle_number}",
        f"Chassis No: {vehicle.chassis_number}",
        f"Engine No: {vehicle.engine_number or 'N/A'}",
        f"Owner: {vehicle.owner_name}",
        f"Mobile: {vehicle.mobile_number}",
        f"Type: {vehicle.vehicle_type or 'N/A'}",
        f"District: {vehicle.district or 'N/A'}",
        f"Registration: {vehicle.registration_date.strftime('%d-%m-%Y') if vehicle.registration_date else 'N/A'}",
        "",
        "--- Document Status ---",
        f"PUC Expiry: {vehicle.puc_expiry.strftime('%d-%m-%Y') if vehicle.puc_expiry else 'Not Set'}",
        f"Fitness Expiry: {vehicle.fitness_expiry.strftime('%d-%m-%Y') if vehicle.fitness_expiry else 'Not Set'}",
        f"Permit Expiry: {vehicle.permit_expiry.strftime('%d-%m-%Y') if vehicle.permit_expiry else 'Not Set'}",
        f"Tax Expiry: {vehicle.tax_expiry.strftime('%d-%m-%Y') if vehicle.tax_expiry else 'Not Set'}",
        f"Tax Mode: {vehicle.tax_mode or 'N/A'}",
        f"Tax Amount: {vehicle.tax_amount or 'N/A'}",
        f"Insurance Expiry: {vehicle.insurance_expiry.strftime('%d-%m-%Y') if vehicle.insurance_expiry else 'Not Set'}",
        f"National Permit: {vehicle.national_permit_expiry.strftime('%d-%m-%Y') if vehicle.national_permit_expiry else 'Not Set'}",
        f"State Permit: {vehicle.state_permit_expiry.strftime('%d-%m-%Y') if vehicle.state_permit_expiry else 'Not Set'}",
        "",
        f"Insurance Co: {vehicle.insurance_company or 'N/A'}",
        f"Policy No: {vehicle.policy_number or 'N/A'}",
        f"Pollution Cert: {vehicle.pollution_certificate_number or 'N/A'}",
        "",
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
        "VEHICLE EXPIRY ALERT",
        f"{'=' * 30}",
        "",
        f"Vehicle No : {vehicle.vehicle_number}",
        f"Chassis No : {vehicle.chassis_number}",
        f"Owner      : {vehicle.owner_name}",
        f"Mobile     : {vehicle.mobile_number}",
        f"Type       : {vehicle.vehicle_type or 'N/A'}",
        f"District   : {vehicle.district or 'N/A'}",
        "",
        "--- Expired / Expiring Documents ---",
        "",
    ]

    for label, expiry, days_left in expired_docs:
        date_str = expiry.strftime('%d-%m-%Y')
        if days_left < 0:
            lines.append(f"{label} : Expired on {date_str} ({abs(days_left)} days ago)")
        elif days_left == 0:
            lines.append(f"{label} : Expires today ({date_str})")
        else:
            lines.append(f"{label} : Expires on {date_str} ({days_left} days left)")

    lines.append("")
    lines.append("Please renew immediately to avoid penalties.")

    return "\n".join(lines)
