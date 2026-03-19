"""Shared authentication helpers for FrameCast."""

import functools
import logging

from flask import Response, request

from modules import config

log = logging.getLogger(__name__)

# Read once at import; matches web_upload.py behavior.
WEB_PASSWORD = config.get("WEB_PASSWORD", "").strip()


def _check_auth(username, password):
    """Verify credentials against the configured WEB_PASSWORD."""
    return password == WEB_PASSWORD


def _auth_required_response():
    """Return a 401 response that prompts for Basic Auth."""
    return Response(
        "Authentication required. Please provide the configured PIN.",
        401,
        {"WWW-Authenticate": 'Basic realm="Pi Photo Display"'},
    )


def require_pin(f):
    """Decorator to require HTTP Basic Auth when WEB_PASSWORD is set.

    If WEB_PASSWORD is empty or not configured, the route is unprotected
    (preserving the default open-access behavior for local networks).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not WEB_PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _auth_required_response()
        return f(*args, **kwargs)
    return decorated
