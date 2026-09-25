"""Authentication middleware (single-user session login)."""
import logging
from functools import wraps

from flask import redirect, request, session, url_for

from app.config import Config

logger = logging.getLogger(__name__)


def login_required(view):
    """Redirect unauthenticated users to the login page when login is required."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if Config.LOGIN_REQUIRED and not session.get("logged_in"):
            return redirect(url_for("auth.login", next=request.path))
        if not Config.LOGIN_REQUIRED and not session.get("logged_in"):
            logger.warning("LOGIN_REQUIRED=false: unauthenticated access to %s from %s",
                           request.path, request.remote_addr)
        return view(*args, **kwargs)
    return wrapped
