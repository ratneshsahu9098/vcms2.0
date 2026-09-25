"""HTTP route blueprints, one per domain. URLs are unchanged from the
pre-refactor app; endpoint names are prefixed with the blueprint name
(e.g. vehicles.view_vehicle)."""
from app.routes import (ai, api, auth, backup, dashboard, data, email,
                        reminders, settings, tax, vehicles)

BLUEPRINTS = (
    auth.bp,
    dashboard.bp,
    vehicles.bp,
    email.bp,
    reminders.bp,
    data.bp,
    backup.bp,
    settings.bp,
    tax.bp,
    api.bp,
    ai.bp,
)


def register_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
