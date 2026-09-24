import os
import smtplib
import logging
import requests
from datetime import date, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

MAILGUN_API_URL = "https://api.mailgun.net/v3/{domain}/messages"


def _get_settings():
    from utils import load_settings
    return load_settings()


def get_smtp_config():
    settings = _get_settings()
    return {
        "server": settings.get("smtp_server", os.environ.get("VCMS_SMTP_SERVER", "smtp.gmail.com")),
        "port": int(settings.get("smtp_port", os.environ.get("VCMS_SMTP_PORT", "587"))),
        "user": settings.get("smtp_user", os.environ.get("VCMS_SMTP_USER", "")),
        "password": settings.get("smtp_password", os.environ.get("VCMS_SMTP_PASSWORD", "")),
        "from_email": settings.get("smtp_from", os.environ.get("VCMS_SMTP_FROM", "")),
    }


def get_mailgun_config():
    settings = _get_settings()
    return {
        "api_key": settings.get("mailgun_api_key", os.environ.get("VCMS_MAILGUN_KEY", "")),
        "domain": settings.get("mailgun_domain", os.environ.get("VCMS_MAILGUN_DOMAIN", "")),
        "from_email": settings.get("mailgun_from", os.environ.get("VCMS_MAILGUN_FROM", "")),
    }


def is_mailgun_configured():
    cfg = get_mailgun_config()
    return bool(cfg["api_key"] and cfg["domain"])


def is_configured():
    return is_mailgun_configured() or _is_smtp_configured()


def _is_smtp_configured():
    cfg = get_smtp_config()
    return bool(cfg["user"] and cfg["password"])


def send_email(to_email, subject, html_body):
    logger.info(f"send_email to={to_email}: smtp={_is_smtp_configured()}, mailgun={is_mailgun_configured()}")
    if _is_smtp_configured():
        result = send_email_via_smtp(to_email, subject, html_body)
        logger.info(f"SMTP result: {result}")
        if result.get("ok"):
            return result
        logger.warning(f"SMTP failed, falling back to Mailgun: {result.get('error')}")

    if is_mailgun_configured():
        return send_email_via_mailgun(to_email, subject, html_body)

    return {"ok": False, "error": "No email provider configured. Set SMTP or Mailgun in Settings."}


def send_email_via_mailgun(to_email, subject, html_body):
    cfg = get_mailgun_config()
    api_url = MAILGUN_API_URL.format(domain=cfg["domain"])
    from_addr = cfg["from_email"] or f"VCMS <postmaster@{cfg['domain']}>"

    try:
        resp = requests.post(
            api_url,
            auth=("api", cfg["api_key"]),
            data={
                "from": from_addr,
                "to": to_email,
                "subject": subject,
                "html": html_body,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return {"ok": True}
        elif resp.status_code == 403:
            return {"ok": False, "error": f"Mailgun: recipient not authorized. Add '{to_email}' in Mailgun dashboard → Sending → Authorized recipients."}
        else:
            return {"ok": False, "error": f"Mailgun HTTP {resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Mailgun request timed out (30s)."}
    except Exception as e:
        logger.exception("Mailgun send failed")
        return {"ok": False, "error": str(e)}


def send_email_via_smtp(to_email, subject, html_body):
    cfg = get_smtp_config()
    if not cfg["user"] or not cfg["password"]:
        return {"ok": False, "error": "SMTP not configured. Set email in Settings."}

    msg = MIMEMultipart("alternative")
    msg["From"] = cfg["from_email"] or cfg["user"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_email"] or cfg["user"], to_email, msg.as_string())
        server.quit()
        return {"ok": True}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "SMTP login failed. Check email/password (use App Password for Gmail)."}
    except smtplib.SMTPRecipientsRefused:
        return {"ok": False, "error": f"Recipient rejected: {to_email}"}
    except Exception as e:
        logger.exception("Email send failed")
        return {"ok": False, "error": str(e)}


def build_reminder_body(vehicle):
    today = date.today()
    statuses = vehicle.document_statuses()
    expiry_lines = []
    has_urgent = False

    for label, info in statuses.items():
        expiry = info["expiry"]
        if expiry is None:
            continue
        days_left = (expiry - today).days
        date_str = expiry.strftime("%d-%b-%Y")
        if days_left < 0:
            color = "#dc2626"
            status_text = f"EXPIRED {abs(days_left)} days ago"
            has_urgent = True
        elif days_left == 0:
            color = "#ea580c"
            status_text = "EXPIRES TODAY"
            has_urgent = True
        elif days_left <= 7:
            color = "#ea580c"
            status_text = f"{days_left} days left"
            has_urgent = True
        elif days_left <= 30:
            color = "#ca8a04"
            status_text = f"{days_left} days left"
        else:
            color = "#16a34a"
            status_text = f"{days_left} days left"
        expiry_lines.append((label, date_str, status_text, color))

    if not expiry_lines:
        return None, False

    table_rows = ""
    for label, date_str, status_text, color in expiry_lines:
        table_rows += f"""
        <tr>
          <td style="padding:10px 14px; border-bottom:1px solid #e5e7eb; font-weight:600;">{label}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #e5e7eb;">{date_str}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #e5e7eb; color:{color}; font-weight:600;">{status_text}</td>
        </tr>"""

    subject_prefix = "URGENT:" if has_urgent else "Reminder:"
    subject = f"{subject_prefix} Document Expiry for {vehicle.vehicle_number}"

    html = f"""
    <div style="font-family:'Segoe UI',Roboto,sans-serif; max-width:600px; margin:0 auto; background:#f5f6fa; padding:20px;">
      <div style="background:#1f2229; padding:20px 24px; border-radius:12px 12px 0 0;">
        <h2 style="color:#e6e8ec; margin:0;">
          <span style="color:#3b82f6;">&#128663;</span> VCMS Expiry Reminder
        </h2>
      </div>
      <div style="background:#ffffff; padding:24px; border-radius:0 0 12px 12px; border:1px solid #e5e7eb;">
        <p style="color:#374151; margin:0 0 16px;">Dear <strong>{vehicle.owner_name}</strong>,</p>
        <p style="color:#374151; margin:0 0 16px;">This is a reminder that the following documents for your vehicle are expiring soon:</p>

        <div style="background:#f9fafb; border-radius:8px; padding:14px; margin-bottom:16px;">
          <table style="width:100%; border-collapse:collapse;">
            <tr>
              <td style="color:#6b7280; font-size:12px; text-transform:uppercase;">Vehicle Number</td>
              <td style="font-weight:700; font-size:16px; color:#1f2229;">{vehicle.vehicle_number}</td>
            </tr>
            <tr>
              <td style="color:#6b7280; font-size:12px; text-transform:uppercase;">Chassis Number</td>
              <td style="color:#374151;">{vehicle.chassis_number}</td>
            </tr>
            <tr>
              <td style="color:#6b7280; font-size:12px; text-transform:uppercase;">Owner</td>
              <td style="color:#374151;">{vehicle.owner_name}</td>
            </tr>
          </table>
        </div>

        <table style="width:100%; border-collapse:collapse; border:1px solid #e5e7eb; border-radius:8px; overflow:hidden;">
          <thead>
            <tr style="background:#f3f4f6;">
              <th style="padding:10px 14px; text-align:left; font-size:12px; text-transform:uppercase; color:#6b7280;">Document</th>
              <th style="padding:10px 14px; text-align:left; font-size:12px; text-transform:uppercase; color:#6b7280;">Expiry Date</th>
              <th style="padding:10px 14px; text-align:left; font-size:12px; text-transform:uppercase; color:#6b7280;">Status</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>

        <p style="color:#dc2626; font-weight:600; margin:20px 0 8px;">Please renew immediately to avoid penalties.</p>
        <p style="color:#6b7280; font-size:12px; margin:0;">This is an automated reminder from VCMS — Vehicle Compliance Management System.</p>
      </div>
    </div>"""

    return html, has_urgent


def send_reminder(vehicle, force=False):
    if not vehicle.owner_email:
        return {"ok": False, "error": "No email address set for this vehicle"}

    from models import db, ReminderLog
    today = date.today()
    statuses = vehicle.document_statuses()

    docs_to_remind = []
    for label, info in statuses.items():
        expiry = info["expiry"]
        if expiry is None:
            continue
        days_left = (expiry - today).days
        if days_left > 30:
            continue

        if not force:
            existing = ReminderLog.query.filter_by(
                vehicle_id=vehicle.id,
                document_type=label,
                recipient_email=vehicle.owner_email,
            ).filter(
                ReminderLog.sent_at >= datetime.combine(today, datetime.min.time())
            ).first()
            if existing:
                continue

        docs_to_remind.append(label)

    if not docs_to_remind:
        return {"ok": True, "sent": []}

    html_body, _ = build_reminder_body(vehicle)
    if not html_body:
        return {"ok": True, "sent": []}

    result = send_email(
        vehicle.owner_email,
        f"VCMS Reminder: Document Expiry for {vehicle.vehicle_number}",
        html_body,
    )

    for label in docs_to_remind:
        log = ReminderLog(
            vehicle_id=vehicle.id,
            document_type=label,
            recipient_email=vehicle.owner_email,
            status="sent" if result.get("ok") else "failed",
            error_message=result.get("error", ""),
        )
        db.session.add(log)

    db.session.commit()
    return {"ok": True, "sent": docs_to_remind}


def build_consolidated_reminder_html(owner_name, vehicle_cards, total_vehicles, expired_count, expiring_count):
    cards_html = ""
    for idx, (v, doc_rows) in enumerate(vehicle_cards):
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        cards_html += f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">
          <tr>
            <td style="background:linear-gradient(135deg,#1e293b 0%,#334155 100%); padding:16px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:18px; font-weight:700; color:#ffffff; letter-spacing:0.5px; vertical-align:middle;">{v.vehicle_number}
                    <span style="font-size:12px; color:#94a3b8; font-weight:400; margin-left:8px;">{v.sr_no or ''}</span>
                  </td>
                  <td align="right" style="font-size:12px; color:#94a3b8; vertical-align:middle;">{v.vehicle_type or ''}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 20px; background:{bg};">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="25%" style="vertical-align:top; padding:0 12px 0 0;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Owner</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{v.owner_name or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Mobile</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{v.mobile_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Chassis</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{v.chassis_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 0 0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Engine</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{v.engine_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 20px 20px 20px; background:{bg};">
              <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
                <tr style="background:#f1f5f9;">
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Document</td>
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Expiry Date</td>
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Status</td>
                </tr>
                {doc_rows}
              </table>
            </td>
          </tr>
        </table>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0; padding:0; background:#f1f5f9; font-family:'Segoe UI',Roboto,-apple-system,sans-serif;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
        <tr>
          <td align="center" style="padding:30px 16px;">
            <table role="presentation" width="680" cellpadding="0" cellspacing="0" style="max-width:680px; width:100%;">

              <!-- HEADER -->
              <tr>
                <td style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#334155 100%); padding:32px 40px; border-radius:16px 16px 0 0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="vertical-align:middle;">
                        <div style="font-size:28px; font-weight:800; color:#ffffff; letter-spacing:-0.5px;">VCMS</div>
                        <div style="font-size:13px; color:#94a3b8; margin-top:4px; letter-spacing:0.3px;">Vehicle Compliance Management System</div>
                      </td>
                      <td align="right" style="vertical-align:middle;">
                        <table cellpadding="0" cellspacing="0" style="margin-left:auto;">
                          <tr>
                            <td style="background:rgba(234,88,12,0.15); border:1px solid rgba(234,88,12,0.3); border-radius:10px; padding:12px 20px; text-align:center;">
                              <div style="font-size:28px; font-weight:800; color:#ea580c; line-height:1;">{total_vehicles}</div>
                              <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Expiring Vehicles</div>
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- STATS BAR -->
              <tr>
                <td style="background:#ffffff; padding:20px 40px; border-bottom:1px solid #e2e8f0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td width="50%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#dc2626; line-height:1;">{expired_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expired</div>
                      </td>
                      <td width="50%" align="center" style="padding:12px 8px;">
                        <div style="font-size:24px; font-weight:700; color:#ea580c; line-height:1;">{expiring_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expiring Soon</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- GREETING -->
              <tr>
                <td style="background:#ffffff; padding:24px 40px 0 40px;">
                  <p style="color:#374151; margin:0 0 8px; font-size:15px;">Dear <strong>{owner_name}</strong>,</p>
                  <p style="color:#374151; margin:0 0 20px; font-size:15px;">This is a reminder that the following documents for your vehicles are expiring soon. Please renew them immediately to avoid penalties.</p>
                </td>
              </tr>

              <!-- VEHICLE CARDS -->
              <tr>
                <td style="background:#ffffff; padding:0 40px 24px 40px;">
                  {cards_html}
                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#f8fafc; padding:24px 40px; border-radius:0 0 16px 16px; border-top:1px solid #e2e8f0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="vertical-align:middle;">
                        <div style="font-size:12px; color:#94a3b8;">Sent on {datetime.now().strftime("%d %B %Y at %I:%M %p")}</div>
                        <div style="font-size:11px; color:#cbd5e1; margin-top:6px;">This is an automated reminder from VCMS &mdash; Vehicle Compliance Management System</div>
                      </td>
                      <td align="right" style="vertical-align:middle;">
                        <div style="font-size:20px; font-weight:800; color:#e2e8f0; letter-spacing:-0.5px;">VCMS</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>"""
    return html


def _get_expiring_docs(vehicle, today, max_days=30):
    statuses = vehicle.document_statuses()
    expiry_lines = []
    for label, info in statuses.items():
        expiry = info["expiry"]
        if expiry is None:
            continue
        days_left = (expiry - today).days
        if days_left > max_days:
            continue
        date_str = expiry.strftime("%d-%b-%Y")
        if days_left < 0:
            color = "#dc2626"
            status_text = f"EXPIRED {abs(days_left)} days ago"
            badge_bg = "#fef2f2"; badge_color = "#dc2626"; badge_border = "#fecaca"
        elif days_left == 0:
            color = "#ea580c"
            status_text = "EXPIRES TODAY"
            badge_bg = "#fff7ed"; badge_color = "#ea580c"; badge_border = "#fed7aa"
        elif days_left <= 7:
            color = "#ea580c"
            status_text = f"{days_left} days left"
            badge_bg = "#fff7ed"; badge_color = "#ea580c"; badge_border = "#fed7aa"
        elif days_left <= 30:
            color = "#ca8a04"
            status_text = f"{days_left} days left"
            badge_bg = "#fefce8"; badge_color = "#ca8a04"; badge_border = "#fef08a"
        expiry_lines.append((label, date_str, status_text, color, badge_bg, badge_color, badge_border))
    return expiry_lines


def _build_vehicle_doc_rows(expiry_lines):
    doc_rows = ""
    for label, date_str, status_text, color, badge_bg, badge_color, badge_border in expiry_lines:
        doc_rows += f"""
        <tr>
          <td style="padding:10px 14px; font-size:13px; color:#374151; font-weight:500; border-bottom:1px solid #f1f5f9;">{label}</td>
          <td style="padding:10px 14px; font-size:13px; color:#6b7280; border-bottom:1px solid #f1f5f9;">{date_str}</td>
          <td style="padding:10px 14px; border-bottom:1px solid #f1f5f9;">
            <span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background:{badge_bg}; color:{badge_color}; border:1px solid {badge_border};">{status_text}</span>
          </td>
        </tr>"""
    return doc_rows


def send_consolidated_reminders(vehicles, force=False):
    from models import ReminderLog, db

    today = date.today()
    by_owner = {}
    for v in vehicles:
        if not v.owner_email:
            continue
        expiry_lines = _get_expiring_docs(v, today, max_days=30)
        if not expiry_lines:
            continue
        by_owner.setdefault(v.owner_email, []).append((v, expiry_lines))

    results = {"emails_sent": 0, "failed": 0, "skipped": 0, "total_vehicles": 0}

    for email, vehicle_list in by_owner.items():
        owner_name = vehicle_list[0][0].owner_name

        vehicle_cards = []
        expired_count = 0
        expiring_count = 0
        for v, expiry_lines in vehicle_list:
            doc_rows = _build_vehicle_doc_rows(expiry_lines)
            vehicle_cards.append((v, doc_rows))
            for _, _, status_text, _, _, _, _ in expiry_lines:
                if "EXPIRED" in status_text or "EXPIRES TODAY" in status_text:
                    expired_count += 1
                else:
                    expiring_count += 1

        html_body = build_consolidated_reminder_html(
            owner_name, vehicle_cards, len(vehicle_cards), expired_count, expiring_count
        )

        vehicle_numbers = ", ".join(v.vehicle_number for v, _ in vehicle_list)
        subject = f"VCMS Reminder: Document Expiry for {len(vehicle_cards)} vehicle(s) — {vehicle_numbers}"

        result = send_email(email, subject, html_body)

        for v, expiry_lines in vehicle_list:
            for label, _, _, _, _, _, _ in expiry_lines:
                if not force:
                    existing = ReminderLog.query.filter_by(
                        vehicle_id=v.id,
                        document_type=label,
                        recipient_email=email,
                    ).filter(
                        ReminderLog.sent_at >= datetime.combine(today, datetime.min.time())
                    ).first()
                    if existing:
                        continue

                log = ReminderLog(
                    vehicle_id=v.id,
                    document_type=label,
                    recipient_email=email,
                    status="sent" if result.get("ok") else "failed",
                    error_message=result.get("error", ""),
                )
                db.session.add(log)

        if result.get("ok"):
            results["emails_sent"] += 1
            results["total_vehicles"] += len(vehicle_list)
        else:
            results["failed"] += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return results


def send_bulk_reminders(force=False):
    from models import Vehicle
    vehicles = Vehicle.query.filter(Vehicle.owner_email.isnot(None)).filter(Vehicle.owner_email != "").all()
    return send_consolidated_reminders(vehicles, force=force)


def send_test_email(to_email):
    html = """
    <div style="font-family:'Segoe UI',Roboto,sans-serif; max-width:600px; margin:0 auto; background:#f5f6fa; padding:20px;">
      <div style="background:#1f2229; padding:20px 24px; border-radius:12px 12px 0 0;">
        <h2 style="color:#e6e8ec; margin:0;">
          <span style="color:#3b82f6;">&#9989;</span> VCMS Email Test
        </h2>
      </div>
      <div style="background:#ffffff; padding:24px; border-radius:0 0 12px 12px; border:1px solid #e5e7eb;">
        <p style="color:#374151;">This is a test email from <strong>VCMS — Vehicle Compliance Management System</strong>.</p>
        <p style="color:#374151;">If you received this, your email configuration is working correctly.</p>
        <p style="color:#6b7280; font-size:12px; margin-top:20px;">Sent at: """ + datetime.now().strftime("%d %b %Y, %I:%M %p") + """</p>
      </div>
    </div>"""
    return send_email(to_email, "VCMS Email Test", html)


def send_all_vehicle_details(to_email, vehicle_ids=None):
    from models import Vehicle
    if vehicle_ids:
        vehicles = Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all()
    else:
        vehicles = Vehicle.query.all()

    if not vehicles:
        return {"ok": False, "error": "No vehicles found."}

    total = len(vehicles)
    expired_count = 0
    expiring_soon = 0
    valid_count = 0

    vehicle_cards = ""
    for idx, v in enumerate(vehicles):
        statuses = v.document_statuses()
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"

        doc_rows = ""
        for label in ["PUC", "Fitness", "Permit", "Tax", "Insurance"]:
            info = statuses.get(label, {})
            exp = info.get("expiry")
            cls = info.get("class", "")
            status_text = info.get("status", "Not Set")

            if "red" in cls:
                badge_bg = "#fef2f2"; badge_color = "#dc2626"; badge_border = "#fecaca"
                expired_count += 1
            elif "orange" in cls:
                badge_bg = "#fff7ed"; badge_color = "#ea580c"; badge_border = "#fed7aa"
                expiring_soon += 1
            elif "yellow" in cls:
                badge_bg = "#fefce8"; badge_color = "#ca8a04"; badge_border = "#fef08a"
                expiring_soon += 1
            elif "green" in cls:
                badge_bg = "#f0fdf4"; badge_color = "#16a34a"; badge_border = "#bbf7d0"
                valid_count += 1
            else:
                badge_bg = "#f9fafb"; badge_color = "#6b7280"; badge_border = "#e5e7eb"

            date_str = exp.strftime("%d %b %Y") if exp else "Not Set"
            doc_rows += f"""
            <tr>
              <td style="padding:10px 14px; font-size:13px; color:#374151; font-weight:500; border-bottom:1px solid #f1f5f9;">{label}</td>
              <td style="padding:10px 14px; font-size:13px; color:#6b7280; border-bottom:1px solid #f1f5f9;">{date_str}</td>
              <td style="padding:10px 14px; border-bottom:1px solid #f1f5f9;">
                <span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background:{badge_bg}; color:{badge_color}; border:1px solid {badge_border};">{status_text}</span>
              </td>
            </tr>"""

        vehicle_cards += f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">
          <!-- Vehicle Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1e293b 0%,#334155 100%); padding:16px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:18px; font-weight:700; color:#ffffff; letter-spacing:0.5px; vertical-align:middle;">{v.vehicle_number}
                    <span style="font-size:12px; color:#94a3b8; font-weight:400; margin-left:8px;">{v.sr_no or ''}</span>
                  </td>
                  <td align="right" style="font-size:12px; color:#94a3b8; vertical-align:middle;">{v.vehicle_type or ''}</td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Vehicle Info -->
          <tr>
            <td style="padding:18px 20px; background:{bg};">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="25%" style="vertical-align:top; padding:0 12px 0 0;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Owner</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{v.owner_name or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Mobile</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{v.mobile_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Chassis</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{v.chassis_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                  <td width="1%" style="padding:0;"><div style="width:1px; background:#e2e8f0; height:100%; min-height:40px;">&nbsp;</div></td>
                  <td width="24%" style="vertical-align:top; padding:0 0 0 12px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px; padding-bottom:5px;">Engine</td>
                      </tr>
                      <tr>
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{v.engine_number or '—'}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Document Table -->
          <tr>
            <td style="padding:0 20px 20px 20px; background:{bg};">
              <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
                <tr style="background:#f1f5f9;">
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Document</td>
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Expiry Date</td>
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Status</td>
                </tr>
                {doc_rows}
              </table>
            </td>
          </tr>
        </table>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0; padding:0; background:#f1f5f9; font-family:'Segoe UI',Roboto,-apple-system,sans-serif;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
        <tr>
          <td align="center" style="padding:30px 16px;">
            <table role="presentation" width="680" cellpadding="0" cellspacing="0" style="max-width:680px; width:100%;">

              <!-- HEADER -->
              <tr>
                <td style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#334155 100%); padding:32px 40px; border-radius:16px 16px 0 0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="vertical-align:middle;">
                        <div style="font-size:28px; font-weight:800; color:#ffffff; letter-spacing:-0.5px;">VCMS</div>
                        <div style="font-size:13px; color:#94a3b8; margin-top:4px; letter-spacing:0.3px;">Vehicle Compliance Management System</div>
                      </td>
                      <td align="right" style="vertical-align:middle;">
                        <table cellpadding="0" cellspacing="0" style="margin-left:auto;">
                          <tr>
                            <td style="background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.3); border-radius:10px; padding:12px 20px; text-align:center;">
                              <div style="font-size:28px; font-weight:800; color:#3b82f6; line-height:1;">{total}</div>
                              <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; margin-top:4px;">Vehicles</div>
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- STATS BAR -->
              <tr>
                <td style="background:#ffffff; padding:20px 40px; border-bottom:1px solid #e2e8f0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td width="33%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#16a34a; line-height:1;">{valid_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Valid</div>
                      </td>
                      <td width="33%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#ea580c; line-height:1;">{expiring_soon}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expiring Soon</div>
                      </td>
                      <td width="33%" align="center" style="padding:12px 8px;">
                        <div style="font-size:24px; font-weight:700; color:#dc2626; line-height:1;">{expired_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expired</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- VEHICLE CARDS -->
              <tr>
                <td style="background:#ffffff; padding:24px 40px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="font-size:16px; font-weight:700; color:#1e293b; padding-bottom:16px; border-bottom:2px solid #e2e8f0;">Vehicle Details</td>
                    </tr>
                  </table>
                </td>
              </tr>
              <tr>
                <td style="background:#ffffff; padding:0 40px 24px 40px;">
                  {vehicle_cards}
                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#f8fafc; padding:24px 40px; border-radius:0 0 16px 16px; border-top:1px solid #e2e8f0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="vertical-align:middle;">
                        <div style="font-size:12px; color:#94a3b8;">Sent on {datetime.now().strftime("%d %B %Y at %I:%M %p")}</div>
                        <div style="font-size:11px; color:#cbd5e1; margin-top:6px;">This is an automated email from VCMS &mdash; Vehicle Compliance Management System</div>
                      </td>
                      <td align="right" style="vertical-align:middle;">
                        <div style="font-size:20px; font-weight:800; color:#e2e8f0; letter-spacing:-0.5px;">VCMS</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>"""

    return send_email(to_email, f"VCMS — {total} Vehicle Details Report", html)


AUTO_REMINDER_WINDOWS = [3, 0]


def auto_reminder_job():
    from models import Vehicle, ReminderLog, db
    from utils import load_settings

    settings = load_settings()
    if not settings.get("auto_reminders_enabled", False):
        logger.info("Auto-reminders disabled, skipping job.")
        return {"sent": 0, "skipped": 0, "failed": 0}

    today = date.today()
    vehicles = Vehicle.query.filter(Vehicle.owner_email.isnot(None)).filter(Vehicle.owner_email != "").all()

    eligible = []
    for v in vehicles:
        statuses = v.document_statuses()
        has_eligible = False
        for label, info in statuses.items():
            expiry = info.get("expiry")
            if expiry is None:
                continue
            days_left = (expiry - today).days
            if days_left not in AUTO_REMINDER_WINDOWS:
                continue
            existing = ReminderLog.query.filter_by(
                vehicle_id=v.id,
                document_type=label,
                recipient_email=v.owner_email,
            ).filter(
                ReminderLog.sent_at >= datetime.combine(today, datetime.min.time())
            ).first()
            if not existing:
                has_eligible = True
                break
        if has_eligible:
            eligible.append(v)

    if not eligible:
        logger.info("Auto-reminder job: no eligible vehicles.")
        return {"sent": 0, "skipped": 0, "failed": 0}

    result = send_consolidated_reminders(eligible, force=False)
    logger.info(f"Auto-reminder job: {result['emails_sent']} emails sent, {result['total_vehicles']} vehicles, {result['failed']} failed")
    return {"sent": result["total_vehicles"], "skipped": 0, "failed": result["failed"]}
