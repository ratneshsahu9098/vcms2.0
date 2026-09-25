"""Application settings UI + API/email connectivity tests."""

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)

from app.middleware import login_required
from app.services import ai_service, email_service, google_drive

bp = Blueprint("settings", __name__)

# ---- Settings ------------------------------------------------------------

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        from app.utils import load_settings, save_settings
        current = load_settings()
        panel = request.form.get("panel", "")

        if panel == "provider":
            provider = request.form.get("ai_provider", "openrouter").strip()
            current["ai_provider"] = provider if provider in ("openrouter", "google") else "openrouter"
        elif panel == "openrouter":
            current["openrouter_api_key"] = request.form.get("openrouter_api_key", "").strip()
            model = request.form.get("openrouter_model", "").strip()
            if model:
                current["openrouter_model"] = model
        elif panel == "google":
            current["google_api_key"] = request.form.get("google_api_key", "").strip()
            google_model = request.form.get("google_model", "").strip()
            if google_model:
                current["google_model"] = google_model
        elif panel == "gdrive":
            current["gdrive_auto_sync"] = request.form.get("gdrive_auto_sync") == "on"
        elif panel == "email":
            _save_email_form_settings()
            flash("Email settings saved.", "success")
            return redirect(url_for("settings.settings"))
        else:
            provider = request.form.get("ai_provider", "openrouter").strip()
            current["ai_provider"] = provider if provider in ("openrouter", "google") else "openrouter"
            current["openrouter_api_key"] = request.form.get("openrouter_api_key", "").strip()
            current["google_api_key"] = request.form.get("google_api_key", "").strip()
            or_model = request.form.get("openrouter_model", "").strip()
            if or_model:
                current["openrouter_model"] = or_model
            g_model = request.form.get("google_model", "").strip()
            if g_model:
                current["google_model"] = g_model
            if "gdrive_auto_sync" in request.form:
                current["gdrive_auto_sync"] = request.form.get("gdrive_auto_sync") == "on"

        save_settings(current)
        flash("Settings saved successfully.", "success")
        return redirect(url_for("settings.settings"))

    from app.utils import load_settings
    ai_settings = load_settings()
    ai_settings["gdrive_connected"] = google_drive.is_connected()
    return render_template("settings.html", ai_settings=ai_settings)

def _save_ai_form_settings(apply_provider=False):
    """Persist AI fields posted from the test forms (only fields present)."""
    from app.utils import load_settings, save_settings
    current = load_settings()
    if apply_provider:
        provider = request.form.get("ai_provider")
        if provider in ("openrouter", "google"):
            current["ai_provider"] = provider
    api_key = request.form.get("openrouter_api_key")
    if api_key is not None:
        current["openrouter_api_key"] = api_key.strip()
    model = request.form.get("openrouter_model")
    if model:
        current["openrouter_model"] = model.strip()
    google_key = request.form.get("google_api_key")
    if google_key is not None:
        current["google_api_key"] = google_key.strip()
    google_model = request.form.get("google_model")
    if google_model:
        current["google_model"] = google_model.strip()
    save_settings(current)
    return current

@bp.route("/settings/test-api", methods=["POST"])
@login_required
def test_api():
    _save_ai_form_settings()
    provider = request.form.get("ai_provider") or None
    result = ai_service.test_api_connection(provider)
    return jsonify(result)

@bp.route("/settings/test-api-debug", methods=["POST"])
@login_required
def test_api_debug():
    _save_ai_form_settings()
    provider = request.form.get("ai_provider") or None
    result = ai_service.test_api_connection_debug(provider)
    return jsonify(result)

def _save_email_form_settings():
    """Persist SMTP email settings posted from the settings/test forms."""
    from app.utils import load_settings, save_settings
    current = load_settings()
    if "smtp_server" in request.form:
        current["smtp_server"] = request.form.get("smtp_server", "smtp.gmail.com").strip() or "smtp.gmail.com"
        current["smtp_port"] = request.form.get("smtp_port", "587").strip() or "587"
        current["smtp_user"] = request.form.get("smtp_user", "").strip()
        current["smtp_password"] = request.form.get("smtp_password", "").strip()
        current["smtp_from"] = request.form.get("smtp_from", "").strip() or current["smtp_user"]
        current["email_reminders_enabled"] = request.form.get("email_reminders_enabled") == "on"
        current["auto_reminders_enabled"] = request.form.get("auto_reminders_enabled") == "on"
        try:
            windows = sorted({int(w) for w in request.form.getlist("auto_reminder_windows")})
        except (TypeError, ValueError):
            windows = [7, 3, 0]
        current["auto_reminder_windows"] = windows
    save_settings(current)
    return current

@bp.route("/settings/test-email", methods=["POST"])
@login_required
def test_email():
    _save_email_form_settings()
    to_email = request.form.get("test_email_to", "").strip()
    if not to_email:
        return jsonify({"ok": False, "error": "No email address provided"})
    result = email_service.send_test_email(to_email)
    return jsonify(result)


