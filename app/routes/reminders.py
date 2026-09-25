"""Email log (/reminders) with status/kind filters."""

from flask import (Blueprint, flash, redirect, render_template, request, url_for)

from app.extensions import db
from app.middleware import login_required
from app.models import (ReminderLog)

bp = Blueprint("reminders", __name__)

@bp.route("/reminders")
@login_required
def reminder_logs():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "").strip()
    kind_filter = request.args.get("kind", "").strip()
    per_page = 50
    query = ReminderLog.query.order_by(ReminderLog.sent_at.desc())
    if status_filter in ("sent", "failed"):
        query = query.filter_by(status=status_filter)
    if kind_filter in ("reminder", "details", "test"):
        query = query.filter_by(kind=kind_filter)
    logs = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template("reminders.html", logs=logs)

@bp.route("/reminders/clear", methods=["POST"])
@login_required
def clear_reminder_logs():
    ReminderLog.query.delete()
    db.session.commit()
    flash("Reminder logs cleared.", "success")
    return redirect(url_for("reminders.reminder_logs"))


