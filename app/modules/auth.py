"""Shared authentication helpers for FrameCast.

Cookie-based PIN auth with open-access fallback.  The PIN is generated at
first boot (see web_upload._ensure_access_pin) and displayed on the TV so
only someone physically present can read it.

Skip list: display routes, SSE, static files, the auth endpoint itself, and
wifi routes when the AP is active are all exempt from PIN checks.
"""

import functools
import logging

from flask import Blueprint, jsonify, make_response, request

from modules import config

log = logging.getLogger(__name__)

COOKIE_NAME = "framecast_pin"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds

auth_api = Blueprint("auth_api", __name__, url_prefix="/api/auth")

# --- Paths that never require a PIN ---
_SKIP_PREFIXES = (
    "/display",
    "/api/events",
    "/api/auth/verify",
    "/static/",
)


def _is_ap_active():
    """Return True when the WiFi hotspot is active (user is physically present)."""
    try:
        from modules.services import is_service_active

        return is_service_active("wifi")
    except Exception:
        log.warning("Failed to check AP status", exc_info=True)
        return False


def _get_access_pin():
    """Read the current ACCESS_PIN from config (live, not cached at import)."""
    return config.get("ACCESS_PIN", "").strip()


def _should_skip_auth():
    """Return True if the current request path is exempt from PIN auth."""
    path = request.path

    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return True

    # WiFi API routes are exempt when the hotspot AP is active
    if path.startswith("/api/wifi") and _is_ap_active():
        return True

    return False


def _pin_is_open_access(pin):
    """Return True if the PIN indicates open-access mode (empty or '0000')."""
    return not pin or pin == "0000"


def require_pin(func):
    """Decorator: require a valid framecast_pin cookie.

    Open access (no PIN or PIN == "0000") bypasses auth entirely.
    Paths on the skip list bypass auth.
    Otherwise, the cookie must match the stored ACCESS_PIN.
    Returns 401 JSON with ``needs_pin: true`` on failure.
    """

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        if _should_skip_auth():
            return func(*args, **kwargs)

        pin = _get_access_pin()
        if _pin_is_open_access(pin):
            return func(*args, **kwargs)

        cookie = request.cookies.get(COOKIE_NAME, "")
        if cookie == pin:
            return func(*args, **kwargs)

        return jsonify({"error": "PIN required", "needs_pin": True}), 401

    return decorated


# --- Auth verification endpoint ---


@auth_api.route("/verify", methods=["POST"])
def verify_pin():
    """Validate a PIN and set an auth cookie on success.

    Accepts JSON: ``{"pin": "1234"}``.
    Returns 200 with cookie on match, 401 on mismatch.
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("pin"), str):
        return jsonify({"error": "Missing or invalid pin field"}), 400

    submitted = data["pin"].strip()
    stored = _get_access_pin()

    if _pin_is_open_access(stored):
        # No PIN configured -- succeed immediately, no cookie needed
        return jsonify({"status": "ok", "message": "AUTHORIZED -- open access"})

    if submitted != stored:
        log.warning("PIN verification failed from %s", request.remote_addr)
        return jsonify({"error": "ACCESS DENIED", "needs_pin": True}), 401

    log.info("PIN verified successfully from %s", request.remote_addr)
    resp = make_response(jsonify({"status": "ok", "message": "AUTHORIZED"}))
    resp.set_cookie(
        COOKIE_NAME,
        value=stored,
        max_age=COOKIE_MAX_AGE,
        samesite="Lax",
        httponly=False,  # JS needs to read it for display
    )
    return resp
