"""Daily auto email reminders via APScheduler (optional dependency)."""
import logging
import os

try:
    from flask_apscheduler import APScheduler
except ImportError:  # pragma: no cover - optional dependency
    APScheduler = None

logger = logging.getLogger(__name__)


def start_scheduler(app):
    """Start the daily cron job that emails document expiry reminders."""
    if APScheduler is None:
        logger.info("Flask-APScheduler not installed; daily auto-reminders disabled.")
        return
    if app.config.get("TESTING"):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return  # avoid double-start under the Werkzeug reloader parent process

    app.config.setdefault("SCHEDULER_API_ENABLED", False)

    scheduler = APScheduler()
    scheduler.init_app(app)

    @scheduler.task("cron", id="daily_email_reminders",
                    hour=app.config.get("EMAIL_REMINDER_HOUR", 9), minute=0)
    def daily_email_reminders():
        with app.app_context():
            from app.utils import load_settings
            from app.services import email_service
            settings = load_settings()
            if not settings.get("auto_reminders_enabled", False):
                return
            try:
                result = email_service.auto_reminder_job()
                logger.info(f"Auto-reminder job: {result}")
            except Exception:
                logger.exception("Auto-reminder job failed")

    try:
        scheduler.start()
        logger.info(f"Scheduler started: daily email reminders at {app.config.get('EMAIL_REMINDER_HOUR', 9)}:00")
    except Exception:
        logger.exception("Scheduler failed to start")
