"""AI chat assistant, document parser and insights."""
from datetime import datetime
import json
import os

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)

from app.config import Config
from app.extensions import db
from app.middleware import login_required
from app.migrations import resequence_sr_nos
from app.models import (ChatMessage, ChatSession, DocumentScan, Vehicle)
from app.services import ai_service, email_service
from app.services.document_service import (build_comparison, find_existing_vehicle,
                                           recent_document_scans, save_document_scan)
from app.utils import (parse_date, to_float)

bp = Blueprint("ai", __name__)

# ---- AI Chat Assistant --------------------------------------------------

def _handle_message(user_msg, session_id=None):
    """Persist the user message, ask AI, persist the reply.

    Returns (chat_session, ai_reply). Shared by the classic form POST and
    the AJAX /ai/chat/send endpoint.
    """
    if session_id:
        chat_session = ChatSession.query.get_or_404(session_id)
    else:
        chat_session = ChatSession(title=user_msg[:80])
        db.session.add(chat_session)
        db.session.commit()

    db.session.add(ChatMessage(session_id=chat_session.id, role="user", content=user_msg))
    db.session.commit()

    history = [{"role": m.role, "content": m.content} for m in chat_session.messages.all()]
    vehicles = Vehicle.query.all()
    try:
        ai_reply = ai_service.ask_assistant(user_msg, vehicles, history=history)
    except Exception as exc:
        ai_reply = f"Error communicating with AI: {exc}"

    db.session.add(ChatMessage(session_id=chat_session.id, role="assistant",
                               content=ai_reply or "No response."))
    chat_session.updated_at = datetime.utcnow()
    db.session.commit()
    return chat_session, ai_reply or "No response."


def _chat_sessions(limit=20):
    return ChatSession.query.order_by(ChatSession.updated_at.desc()).limit(limit).all()


@bp.route("/ai/chat", methods=["GET", "POST"])
@bp.route("/ai/chat/<int:session_id>", methods=["GET", "POST"])
@login_required
def ai_chat(session_id=None):
    if not ai_service.check_api_key():
        flash("API key not configured. Set it in Settings.", "error")
        return render_template("ai_chat.html", messages=[], ai_enabled=False,
                               chat_session=None, sessions=[])

    if request.method == "POST":
        user_msg = request.form.get("message", "").strip()
        if not user_msg:
            flash("Please type a message.", "error")
            return redirect(url_for("ai.ai_chat"))

        sid = request.form.get("session_id")
        chat_session, _reply = _handle_message(user_msg, int(sid) if sid else None)
        return redirect(url_for("ai.ai_chat", session_id=chat_session.id))

    chat_session = None
    messages = []
    if session_id:
        chat_session = ChatSession.query.get_or_404(session_id)
        messages = [{"role": m.role, "content": m.content}
                    for m in chat_session.messages.order_by(ChatMessage.id).all()]

    return render_template("ai_chat.html", messages=messages, ai_enabled=True,
                           chat_session=chat_session, sessions=_chat_sessions())


@bp.route("/ai/chat/send", methods=["POST"])
@login_required
def ai_chat_send():
    """AJAX send: same flow as the classic POST, but answers with JSON."""
    if not ai_service.check_api_key():
        return jsonify(ok=False, error="API key not configured. Set it in Settings."), 503

    user_msg = request.form.get("message", "").strip()
    if not user_msg:
        return jsonify(ok=False, error="Please type a message."), 400

    sid = request.form.get("session_id", type=int)
    chat_session, reply = _handle_message(user_msg, sid)
    return jsonify(
        ok=True,
        session_id=chat_session.id,
        session_url=url_for("ai.ai_chat", session_id=chat_session.id),
        reply=reply,
    )

@bp.route("/ai/chat/new")
@login_required
def ai_chat_new():
    return redirect(url_for("ai.ai_chat"))

@bp.route("/ai/chat/<int:session_id>/delete", methods=["POST"])
@login_required
def ai_chat_delete(session_id):
    chat_session = ChatSession.query.get_or_404(session_id)
    db.session.delete(chat_session)
    db.session.commit()
    flash("Chat deleted.", "success")
    return redirect(url_for("ai.ai_chat_history"))

@bp.route("/ai/chat/history")
@login_required
def ai_chat_history():
    sessions = ChatSession.query.order_by(ChatSession.updated_at.desc()).all()
    return render_template("ai_chat_history.html", sessions=sessions)

# ---- AI Document Parser -------------------------------------------------

def _ocr_pdf(file):
    """Rasterize page 1 of an uploaded PDF and OCR it (needs PyMuPDF)."""
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PDF scanning requires PyMuPDF (pip install PyMuPDF)") from exc
    import io
    import pytesseract
    from PIL import Image
    with pymupdf.open(stream=file.read(), filetype="pdf") as doc:
        if doc.page_count == 0:
            raise RuntimeError("PDF has no pages")
        pix = doc.load_page(0).get_pixmap(dpi=300, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _render_parser(**context):
    context.setdefault("parsed_data", None)
    context.setdefault("last_scans", recent_document_scans())
    context.setdefault("ai_enabled", ai_service.check_api_key())
    return render_template("ai_document_parser.html", **context)


@bp.route("/ai/parse-document", methods=["GET", "POST"])
@login_required
def ai_parse_document():
    if not ai_service.check_api_key():
        flash("AI API key not configured. Set it in Settings.", "error")
        return _render_parser(ai_enabled=False)

    if request.method == "POST":
        file = request.files.get("document")
        if not file or file.filename == "":
            flash("Please upload a document image.", "error")
            return _render_parser()

        try:
            import os
            import pytesseract
            from PIL import Image
            tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.exists(tesseract_path):
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            if (file.filename or "").lower().endswith(".pdf"):
                ocr_text = _ocr_pdf(file)
            else:
                ocr_text = pytesseract.image_to_string(Image.open(file))
        except Exception as exc:
            flash(f"OCR failed: {exc}", "error")
            return _render_parser()

        if not ocr_text.strip():
            flash("No text could be extracted from the image.", "error")
            return _render_parser()

        try:
            parsed_data = ai_service.parse_document_text(ocr_text)
        except Exception as exc:
            flash(f"AI parsing failed: {exc}", "error")
            return _render_parser()

        existing_vehicle = find_existing_vehicle(parsed_data) if parsed_data else None
        scan = save_document_scan(file.filename, parsed_data or {}, ocr_text, existing_vehicle)

        return _render_parser(
            parsed_data=parsed_data,
            ocr_text=ocr_text,
            existing_vehicle=existing_vehicle,
            current_scan_id=scan.id,
            comparison=build_comparison(existing_vehicle, parsed_data) if existing_vehicle else None,
        )

    return _render_parser(existing_vehicle=None)

@bp.route("/ai/parse-document/scan/<int:scan_id>")
@login_required
def ai_parse_view_scan(scan_id):
    """Open a previous scan in the review form (prefilled)."""
    scan = DocumentScan.query.get_or_404(scan_id)
    parsed_data = scan.data_dict()
    if not parsed_data:
        flash("This scan has no extracted data.", "error")
        return redirect(url_for("ai.ai_parse_document"))
    existing = find_existing_vehicle(parsed_data)
    return _render_parser(
        parsed_data=parsed_data,
        ocr_text=scan.ocr_text,
        existing_vehicle=existing,
        current_scan_id=scan.id,
        comparison=build_comparison(existing, parsed_data) if existing else None,
    )

@bp.route("/ai/parse-document/scan/<int:scan_id>/edit", methods=["GET", "POST"])
@login_required
def ai_parse_edit_scan(scan_id):
    """Load a previous scan into the editable form (POST from Recent Scans)."""
    scan = DocumentScan.query.get_or_404(scan_id)
    parsed_data = scan.data_dict()
    if not parsed_data:
        flash("This scan has no extracted data.", "error")
        return redirect(url_for("ai.ai_parse_document"))
    existing = find_existing_vehicle(parsed_data)
    return _render_parser(
        parsed_data=parsed_data,
        ocr_text=scan.ocr_text,
        existing_vehicle=existing,
        current_scan_id=scan.id,
        comparison=build_comparison(existing, parsed_data) if existing else None,
    )

@bp.route("/ai/parse-document/add", methods=["POST"])
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
            "owner_email": email_service.normalize_emails(request.form.get("owner_email", "")),
            "vehicle_type": request.form.get("vehicle_type", "").strip(),
            "registration_date": parse_date(request.form.get("registration_date")),
            "puc_expiry": parse_date(request.form.get("puc_expiry")),
            "fitness_expiry": parse_date(request.form.get("fitness_expiry")),
            "permit_expiry": parse_date(request.form.get("permit_expiry")),
            "permit_from": parse_date(request.form.get("permit_from")),
            "permit_auth_no": request.form.get("permit_auth_no", "").strip(),
            "permit_address": request.form.get("permit_address", "").strip(),
            "insurance_expiry": parse_date(request.form.get("insurance_expiry")),
            "insurance_company": request.form.get("insurance_company", "").strip(),
            "policy_number": request.form.get("policy_number", "").strip(),
            "tax_from": parse_date(request.form.get("tax_from")),
            "tax_expiry": parse_date(request.form.get("tax_expiry")),
            "tax_mode": request.form.get("tax_mode", "").strip(),
            "tax_amount": to_float(request.form.get("tax_amount")),
        }
        accepted = set(request.form.getlist("accepted_fields"))
        updated_fields = []
        for item in build_comparison(existing, updates):
            if item["status"] != "empty" and item["field"] not in accepted:
                continue
            value = updates.get(item["field"])
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            setattr(existing, item["field"], value)
            updated_fields.append(item["field"])

        existing.updated_at = datetime.utcnow()
        db.session.commit()
        if scan_id:
            scan = DocumentScan.query.get(scan_id)
            if scan:
                scan.vehicle_id = existing.id
                db.session.commit()
        flash(f"Vehicle {existing.vehicle_number} updated with {len(updated_fields)} new fields.", "success")
        return redirect(url_for("vehicles.view_vehicle", vehicle_id=existing.id))

    vehicle = Vehicle(
        vehicle_number=vnum,
        chassis_number=chassis,
        engine_number=request.form.get("engine_number", "").strip().upper(),
        owner_name=request.form.get("owner_name", "").strip(),
        mobile_number=request.form.get("mobile_number", "").strip(),
        owner_email=email_service.normalize_emails(request.form.get("owner_email", "")),
        vehicle_type=request.form.get("vehicle_type", "").strip(),
        registration_date=parse_date(request.form.get("registration_date")),
        puc_expiry=parse_date(request.form.get("puc_expiry")),
        fitness_expiry=parse_date(request.form.get("fitness_expiry")),
        permit_expiry=parse_date(request.form.get("permit_expiry")),
        permit_from=parse_date(request.form.get("permit_from")),
        permit_auth_no=request.form.get("permit_auth_no", "").strip(),
        permit_address=request.form.get("permit_address", "").strip(),
        insurance_expiry=parse_date(request.form.get("insurance_expiry")),
        insurance_company=request.form.get("insurance_company", "").strip(),
        policy_number=request.form.get("policy_number", "").strip(),
        tax_from=parse_date(request.form.get("tax_from")),
        tax_expiry=parse_date(request.form.get("tax_expiry")),
        tax_mode=request.form.get("tax_mode", "").strip(),
        tax_amount=to_float(request.form.get("tax_amount")),
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
    return redirect(url_for("vehicles.vehicle_list"))

# ---- AI Insights --------------------------------------------------------

def _load_cached_insights():
    try:
        with open(Config.INSIGHTS_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("insights"):
            return data
    except (OSError, ValueError):
        pass
    return None


def _save_cached_insights(insights):
    try:
        os.makedirs(os.path.dirname(Config.INSIGHTS_CACHE), exist_ok=True)
        with open(Config.INSIGHTS_CACHE, "w", encoding="utf-8") as fh:
            json.dump({"generated_at": datetime.utcnow().isoformat(),
                       "insights": insights}, fh, default=str, ensure_ascii=False)
    except OSError:
        pass


def _generated_label(iso_value):
    if not iso_value:
        return None
    try:
        return datetime.fromisoformat(iso_value).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return None


def _render_insights(insights, generated_at):
    return render_template(
        "ai_insights.html",
        insights=insights,
        ai_enabled=True,
        generated_at=_generated_label(generated_at),
    )


@bp.route("/ai/insights")
@login_required
def ai_insights():
    if not ai_service.check_api_key():
        flash("AI API key not configured. Set it in Settings.", "error")
        return render_template("ai_insights.html", insights=None, ai_enabled=False,
                               generated_at=None)

    cached = _load_cached_insights()
    if cached and request.args.get("refresh") != "1":
        return _render_insights(cached["insights"], cached.get("generated_at"))

    vehicles = Vehicle.query.all()
    try:
        insights = ai_service.generate_insights(vehicles)
    except Exception as exc:
        flash(f"Failed to generate insights: {exc}", "error")
        if cached:
            return _render_insights(cached["insights"], cached.get("generated_at"))
        return render_template("ai_insights.html", insights=None, ai_enabled=True,
                               generated_at=None)

    _save_cached_insights(insights)
    return _render_insights(insights, datetime.utcnow().isoformat())

