import os
import re
import smtplib
import logging
from datetime import date, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def parse_emails(raw):
    """Split a raw owner-email field into a list of addresses.

    Accepts comma / semicolon / whitespace separated values, e.g.
    "a@x.com, b@y.com; c@z.com". Deduplicates case-insensitively.
    """
    if not raw:
        return []
    parts = re.split(r"[,;\s]+", str(raw).strip())
    seen = set()
    out = []
    for p in parts:
        p = p.strip().rstrip(",;")
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def validate_emails(raw):
    """Return (ok, error_message). Empty input is valid (email is optional)."""
    raw = (raw or "").strip()
    if not raw:
        return True, None
    parts = parse_emails(raw)
    if not parts:
        return False, "Owner Email is not valid."
    for p in parts:
        if not EMAIL_RE.match(p):
            return False, f"Owner Email '{p}' is not valid."
    return True, None


def normalize_emails(raw):
    """Return valid addresses joined with ', ' (invalid ones dropped)."""
    return ", ".join(p for p in parse_emails(raw) if EMAIL_RE.match(p))


def _get_settings():
    from app.utils import load_settings
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


def is_configured():
    return _is_smtp_configured()


def _is_smtp_configured():
    cfg = get_smtp_config()
    return bool(cfg["user"] and cfg["password"])


def send_email(to_email, subject, html_body):
    recipients = to_email if isinstance(to_email, (list, tuple)) else parse_emails(to_email)
    recipients = [r for r in recipients if r]
    if not recipients:
        return {"ok": False, "error": "No recipient email address."}
    logger.info(f"send_email to={recipients}: smtp_configured={_is_smtp_configured()}")
    if not _is_smtp_configured():
        return {"ok": False, "error": "SMTP not configured. Set email settings in Settings."}
    result = send_email_via_smtp(recipients, subject, html_body)
    logger.info(f"SMTP result: {result}")
    return result


def send_email_via_smtp(to_email, subject, html_body):
    recipients = to_email if isinstance(to_email, (list, tuple)) else parse_emails(to_email)
    recipients = [r for r in recipients if r]
    if not recipients:
        return {"ok": False, "error": "No recipient email address."}
    cfg = get_smtp_config()
    if not cfg["user"] or not cfg["password"]:
        return {"ok": False, "error": "SMTP not configured. Set email in Settings."}

    msg = MIMEMultipart("alternative")
    msg["From"] = cfg["from_email"] or cfg["user"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    raw_msg = msg.as_string()

    try:
        server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["user"], cfg["password"])
        sent, failed = [], []
        for rcpt in recipients:
            try:
                server.sendmail(cfg["from_email"] or cfg["user"], rcpt, raw_msg)
                sent.append(rcpt)
            except smtplib.SMTPRecipientsRefused:
                failed.append(rcpt)
            except Exception:
                logger.exception(f"Email send failed for {rcpt}")
                failed.append(rcpt)
        server.quit()
        if not sent:
            return {"ok": False, "error": f"Recipient rejected: {', '.join(failed)}"}
        if failed:
            return {"ok": True, "warning": f"Delivered to {', '.join(sent)}; failed for {', '.join(failed)}"}
        return {"ok": True, "recipients": sent}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "SMTP login failed. Check email/password (use App Password for Gmail)."}
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
    recipients = parse_emails(vehicle.owner_email)
    if not recipients:
        return {"ok": False, "error": "No email address set for this vehicle"}

    from app.models import db, ReminderLog
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
        recipients,
        f"VCMS Reminder: Document Expiry for {vehicle.vehicle_number}",
        html_body,
    )
    ok = bool(result.get("ok"))

    for label in docs_to_remind:
        log = ReminderLog(
            vehicle_id=vehicle.id,
            document_type=label,
            recipient_email=vehicle.owner_email,
            status="sent" if ok else "failed",
            error_message=result.get("error", ""),
        )
        db.session.add(log)

    db.session.commit()
    if not ok:
        return {"ok": False, "error": result.get("error") or "SMTP send failed",
                "sent": []}
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
    from app.models import ReminderLog, db

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
    from app.models import Vehicle
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
    result = send_email(to_email, "VCMS Email Test", html)
    log_email_result("test", to_email, result, document_type="Test Email")
    return result


DETAIL_DOC_LABELS = ["PUC", "Fitness", "Permit", "Tax", "Insurance"]


def log_email(kind, recipient, status, error="", vehicle_id=None, document_type=""):
    """Best-effort: record one sent email in reminder_logs (never raises)."""
    from app.models import db, ReminderLog
    try:
        db.session.add(ReminderLog(
            vehicle_id=vehicle_id,
            document_type=(document_type or kind)[:30],
            recipient_email=str(recipient)[:120],
            status=status,
            error_message=error or None,
            kind=kind,
        ))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning(f"Could not write email log ({kind} -> {recipient})", exc_info=True)


def log_email_result(kind, to_email, result, vehicle_id=None, document_type=""):
    """Log a send_email() result as one reminder_logs row per recipient."""
    status = "sent" if result.get("ok") else "failed"
    error = result.get("error") or result.get("warning") or ""
    if isinstance(to_email, (list, tuple)):
        recipients = list(to_email)
    else:
        recipients = parse_emails(to_email)
    if not recipients and to_email:
        recipients = [str(to_email)]
    for r in recipients:
        log_email(kind, r, status, error=error, vehicle_id=vehicle_id, document_type=document_type)


def send_all_vehicle_details(to_email, vehicle_ids=None):
    from html import escape as esc
    from app.models import Vehicle
    if vehicle_ids:
        vehicles = Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all()
    else:
        vehicles = Vehicle.query.all()

    if not vehicles:
        return {"ok": False, "error": "No vehicles found."}

    today = date.today()
    total = len(vehicles)
    expired_count = 0
    expiring_soon = 0
    valid_count = 0

    owner_names = {v.owner_name for v in vehicles if v.owner_name}
    greeting_name = esc(next(iter(owner_names))) if len(owner_names) == 1 else None

    vehicle_cards = ""
    for idx, v in enumerate(vehicles):
        statuses = v.document_statuses()
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"

        doc_rows = ""
        v_expired = 0
        v_orange = 0
        v_yellow = 0
        v_valid = 0
        v_na = 0
        action_docs = []

        for row_idx, label in enumerate(DETAIL_DOC_LABELS):
            info = statuses.get(label, {})
            exp = info.get("expiry")
            cls = info.get("class", "")
            status_text = info.get("status", "Not Set")

            if "red" in cls:
                badge_bg = "#fef2f2"; badge_color = "#dc2626"; badge_border = "#fecaca"
                row_bg = "#fef2f2"; v_expired += 1; expired_count += 1
                action_docs.append(f"{label} (expired)")
            elif "orange" in cls:
                badge_bg = "#fff7ed"; badge_color = "#ea580c"; badge_border = "#fed7aa"
                row_bg = "#fff7ed"; v_orange += 1; expiring_soon += 1
                action_docs.append(f"{label} ({(exp - today).days}d)")
            elif "yellow" in cls:
                badge_bg = "#fefce8"; badge_color = "#ca8a04"; badge_border = "#fef08a"
                row_bg = "#fefce8"; v_yellow += 1; expiring_soon += 1
                action_docs.append(f"{label} ({(exp - today).days}d)")
            elif "green" in cls:
                badge_bg = "#f0fdf4"; badge_color = "#16a34a"; badge_border = "#bbf7d0"
                row_bg = "#ffffff" if row_idx % 2 == 0 else "#f8fafc"
                v_valid += 1; valid_count += 1
            else:
                badge_bg = "#f9fafb"; badge_color = "#6b7280"; badge_border = "#e5e7eb"
                row_bg = "#ffffff" if row_idx % 2 == 0 else "#f8fafc"
                v_na += 1

            if exp is None:
                days_txt, days_color = "&mdash;", "#94a3b8"
            else:
                dl = (exp - today).days
                if dl < 0:
                    days_txt, days_color = f"{abs(dl)}d ago", "#dc2626"
                elif dl == 0:
                    days_txt, days_color = "Today", "#ea580c"
                elif dl <= 7:
                    days_txt, days_color = f"{dl}d left", "#ea580c"
                elif dl <= 30:
                    days_txt, days_color = f"{dl}d left", "#ca8a04"
                else:
                    days_txt, days_color = f"{dl}d left", "#16a34a"

            date_str = exp.strftime("%d %b %Y") if exp else "Not Set"
            doc_rows += f"""
            <tr>
              <td style="padding:10px 14px; font-size:13px; color:#374151; font-weight:500; background:{row_bg}; border-bottom:1px solid #f1f5f9;">{label}</td>
              <td style="padding:10px 14px; font-size:13px; color:#6b7280; background:{row_bg}; border-bottom:1px solid #f1f5f9;">{date_str}</td>
              <td style="padding:10px 14px; font-size:12px; font-weight:600; color:{days_color}; background:{row_bg}; border-bottom:1px solid #f1f5f9;">{days_txt}</td>
              <td style="padding:10px 14px; background:{row_bg}; border-bottom:1px solid #f1f5f9;">
                <span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background:{badge_bg}; color:{badge_color}; border:1px solid {badge_border};">{status_text}</span>
              </td>
            </tr>"""

        if v_expired:
            accent = "#dc2626"; pill_bg = "#fef2f2"; pill_fg = "#dc2626"; pill_bd = "#fecaca"
            pill_text = f"{v_expired} Expired"
        elif v_orange:
            accent = "#ea580c"; pill_bg = "#fff7ed"; pill_fg = "#ea580c"; pill_bd = "#fed7aa"
            pill_text = f"{v_orange} Expiring"
        elif v_yellow:
            accent = "#ca8a04"; pill_bg = "#fefce8"; pill_fg = "#ca8a04"; pill_bd = "#fef08a"
            pill_text = f"{v_yellow} Expiring"
        elif v_na or not v_valid:
            accent = "#cbd5e1"; pill_bg = "#f9fafb"; pill_fg = "#6b7280"; pill_bd = "#e5e7eb"
            pill_text = "Not Set"
        else:
            accent = "#16a34a"; pill_bg = "#f0fdf4"; pill_fg = "#16a34a"; pill_bd = "#bbf7d0"
            pill_text = "All Valid"

        if action_docs:
            strip_row = f"""<tr><td colspan="4" style="background:#fff7ed; border-top:1px solid #fed7aa; padding:11px 16px; font-size:12.5px; color:#c2410c; font-weight:600;">&#9888; Action required: renew {", ".join(action_docs)}</td></tr>"""
        elif v_valid:
            strip_row = """<tr><td colspan="4" style="background:#f0fdf4; border-top:1px solid #bbf7d0; padding:11px 16px; font-size:12.5px; color:#15803d; font-weight:600;">&#10003; All tracked documents are valid.</td></tr>"""
        else:
            strip_row = """<tr><td colspan="4" style="background:#f9fafb; border-top:1px solid #e5e7eb; padding:11px 16px; font-size:12.5px; color:#6b7280; font-weight:600;">No expiry dates set for this vehicle.</td></tr>"""

        dist = f" &middot; {esc(v.district)}" if v.district else ""

        vehicle_cards += f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px; border:1px solid #e2e8f0; border-left:4px solid {accent}; border-radius:12px; overflow:hidden;">
          <!-- Vehicle Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1e293b 0%,#334155 100%); padding:16px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="vertical-align:middle;">
                    <div style="font-size:18px; font-weight:700; color:#ffffff; letter-spacing:0.5px;">{esc(v.vehicle_number)}
                      <span style="font-size:12px; color:#94a3b8; font-weight:400; margin-left:8px;">{esc(v.sr_no or '')}</span>
                    </div>
                    <div style="font-size:11px; color:#94a3b8; margin-top:3px;">{esc(v.vehicle_type or '')}{dist}</div>
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <span style="display:inline-block; padding:5px 12px; border-radius:20px; font-size:11px; font-weight:700; letter-spacing:0.3px; background:{pill_bg}; color:{pill_fg}; border:1px solid {pill_bd};">{pill_text}</span>
                  </td>
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
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{esc(v.owner_name) if v.owner_name else '—'}</td>
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
                        <td style="font-size:14px; font-weight:600; color:#1e293b; line-height:1.4;">{esc(v.mobile_number) if v.mobile_number else '—'}</td>
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
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{esc(v.chassis_number) if v.chassis_number else '—'}</td>
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
                        <td style="font-size:14px; font-weight:600; color:#1e293b; font-family:monospace; line-height:1.4;">{esc(v.engine_number) if v.engine_number else '—'}</td>
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
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Days Left</td>
                  <td style="padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #e2e8f0; text-align:left;">Status</td>
                </tr>
                {doc_rows}
                {strip_row}
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
                        <div style="font-size:11px; color:#60a5fa; text-transform:uppercase; letter-spacing:2px; font-weight:700;">Vehicle Details Report</div>
                        <div style="font-size:28px; font-weight:800; color:#ffffff; letter-spacing:-0.5px; margin-top:6px;">VCMS</div>
                        <div style="font-size:13px; color:#94a3b8; margin-top:4px; letter-spacing:0.3px;">Vehicle Compliance Management System</div>
                        <div style="font-size:12px; color:#64748b; margin-top:12px;">Generated on {today.strftime("%d %B %Y")}</div>
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
                      <td width="25%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#3b82f6; line-height:1;">{total}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Vehicles</div>
                      </td>
                      <td width="25%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#16a34a; line-height:1;">{valid_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Valid</div>
                      </td>
                      <td width="25%" align="center" style="padding:12px 8px; border-right:1px solid #f1f5f9;">
                        <div style="font-size:24px; font-weight:700; color:#ea580c; line-height:1;">{expiring_soon}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expiring Soon</div>
                      </td>
                      <td width="25%" align="center" style="padding:12px 8px;">
                        <div style="font-size:24px; font-weight:700; color:#dc2626; line-height:1;">{expired_count}</div>
                        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px; margin-top:6px;">Expired</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- GREETING -->
              <tr>
                <td style="background:#ffffff; padding:24px 40px 0 40px;">
                  <p style="color:#374151; margin:0 0 8px; font-size:15px;">Dear <strong>{greeting_name or 'Customer'}</strong>,</p>
                  <p style="color:#374151; margin:0; font-size:15px;">Here is the complete compliance details report for <strong>{total} vehicle{'s' if total != 1 else ''}</strong> as on {today.strftime('%d %b %Y')}.</p>
                </td>
              </tr>

              <!-- SECTION HEADING -->
              <tr>
                <td style="background:#ffffff; padding:24px 40px 0 40px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="font-size:16px; font-weight:700; color:#1e293b; vertical-align:middle;">Vehicle Details</td>
                      <td align="right" style="vertical-align:middle;">
                        <span style="display:inline-block; padding:4px 12px; border-radius:20px; font-size:11px; font-weight:700; background:#eff6ff; color:#3b82f6; border:1px solid #bfdbfe;">{total} vehicle{'s' if total != 1 else ''}</span>
                      </td>
                    </tr>
                  </table>
                  <div style="border-bottom:2px solid #e2e8f0; margin-top:12px;"></div>
                </td>
              </tr>
              <tr>
                <td style="background:#ffffff; padding:16px 40px 24px 40px;">
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

    result = send_email(to_email, f"VCMS — {total} Vehicle Details Report", html)
    log_email_result(
        "details", to_email, result,
        vehicle_id=vehicles[0].id if total == 1 else None,
        document_type="All Details" if total == 1 else f"Details ({total} vehicles)",
    )
    return result


DEFAULT_AUTO_REMINDER_WINDOWS = [7, 3, 0]


def get_auto_reminder_windows():
    """Days-before-expiry on which the daily auto job sends reminders."""
    from app.utils import load_settings
    raw = load_settings().get("auto_reminder_windows")
    if raw is None:
        return list(DEFAULT_AUTO_REMINDER_WINDOWS)
    if isinstance(raw, str):
        raw = [w.strip() for w in raw.split(",") if w.strip()]
    try:
        return sorted({int(w) for w in raw})
    except (TypeError, ValueError):
        return list(DEFAULT_AUTO_REMINDER_WINDOWS)


def auto_reminder_job():
    from app.models import Vehicle, ReminderLog
    from app.utils import load_settings

    settings = load_settings()
    if not settings.get("auto_reminders_enabled", False):
        logger.info("Auto-reminders disabled, skipping job.")
        return {"sent": 0, "skipped": 0, "failed": 0}

    windows = get_auto_reminder_windows()
    if not windows:
        logger.info("Auto-reminder windows empty, skipping job.")
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
            if days_left not in windows:
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
    logger.info(
        f"Auto-reminder job (windows={windows}): {result['emails_sent']} emails sent, "
        f"{result['total_vehicles']} vehicles, {result['failed']} failed"
    )
    return {"sent": result["total_vehicles"], "skipped": 0, "failed": result["failed"]}
