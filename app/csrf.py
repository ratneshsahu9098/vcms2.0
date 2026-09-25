"""Session-token CSRF protection for state-changing (POST) requests.

Every HTML form POST must carry a `csrf_token` hidden field (or an
`X-CSRFToken` header for fetch calls); the token lives in the signed
session cookie. Disable with VCMS_CSRF_ENABLED=false if needed.

Exempt specific endpoints with `@csrf.exempt` decorator or by adding
endpoint names to `app.config['CSRF_EXEMPT_ENDPOINTS']`.
"""
import hmac
import secrets

from flask import abort, request, session


# Set of endpoint names exempt from CSRF protection
_exempt_endpoints = set()


def exempt(view):
    """Decorator to exempt a view from CSRF protection."""
    _exempt_endpoints.add(view.__name__)
    return view


def init_csrf(app):
    def csrf_token():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    # jinja global (not context_processor) so direct template.render() in tests works
    app.jinja_env.globals["csrf_token"] = csrf_token

    # Allow config-based exemptions
    config_exempt = set(app.config.get("CSRF_EXEMPT_ENDPOINTS", []))
    all_exempt = _exempt_endpoints | config_exempt

    @app.before_request
    def csrf_protect():
        if request.method != "POST" or not app.config.get("CSRF_ENABLED", True):
            return None
        if request.endpoint in all_exempt:
            return None
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
            abort(400, description="CSRF token missing or invalid.")
        return None
