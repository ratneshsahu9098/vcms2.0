"""Session-token CSRF protection for state-changing (POST) requests.

Every HTML form POST must carry a `csrf_token` hidden field (or an
`X-CSRFToken` header for fetch calls); the token lives in the signed
session cookie. Disable with VCMS_CSRF_ENABLED=false if needed.
"""
import hmac
import secrets

from flask import abort, request, session


def init_csrf(app):
    def csrf_token():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    # jinja global (not context_processor) so direct template.render() in tests works
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def csrf_protect():
        if request.method != "POST" or not app.config.get("CSRF_ENABLED", True):
            return None
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
            abort(400, description="CSRF token missing or invalid.")
        return None
