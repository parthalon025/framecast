"""Shared authentication helpers for FrameCast.

Cookie-based PIN auth with open-access fallback.  The PIN is generated at
first boot (see web_upload._ensure_access_pin) and displayed on the TV so
only someone physically present can read it.

Skip list: display routes, SSE, static files, the auth endpoint itself, and
wifi routes when the AP is active are all exempt from PIN checks.

Security features:
- Configurable PIN length (4 or 6 digits) via PIN_LENGTH setting
- Adaptive rate limiting: 5 attempts for 4-digit, 3 attempts for 6-digit
- Optional PIN rotation on boot (PIN_ROTATE_ON_BOOT=yes)
- SameSite=Strict cookies
- Origin header validation on state-changing requests
"""

import functools
import hashlib
import hmac
import logging
import secrets


from flask import Blueprint, jsonify, make_response, request

from modules import config
from modules.rate_limiter import RateLimiter

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

# --- State-changing HTTP methods that require Origin validation ---
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# --- Rate limiting for PIN verification ---
# 4-digit PIN: 5 attempts / 300s lockout; 6-digit: 3 attempts / 300s lockout
_pin_limiter_4 = RateLimiter(max_attempts=5, window_seconds=300)
_pin_limiter_6 = RateLimiter(max_attempts=3, window_seconds=300)


def _get_pin_length() -> int:
    """Read PIN_LENGTH from config (4 or 6, default 4)."""
    try:
        length = int(config.get("PIN_LENGTH", "4"))
        if length in (4, 6):
            return length
    except (TypeError, ValueError):
        log.warning("Invalid PIN_LENGTH in config, defaulting to 4")
    return 4


def _get_max_attempts() -> int:
    """Return max PIN attempts based on PIN length.

    4-digit PIN: 5 attempts (10,000 combinations)
    6-digit PIN: 3 attempts (1,000,000 combinations — tighter lockout)
    """
    return 3 if _get_pin_length() == 6 else 5


def _get_pin_limiter() -> RateLimiter:
    """Return the appropriate rate limiter for the current PIN length."""
    return _pin_limiter_6 if _get_pin_length() == 6 else _pin_limiter_4


def _make_auth_token(pin):
    """Create an HMAC-SHA256 token from the PIN (never store raw PIN in cookie)."""
    secret = config.get("FLASK_SECRET_KEY", "")
    if not secret:
        log.error("FLASK_SECRET_KEY not set — auth tokens will be insecure")
        # Generate ephemeral key for this session (forces PIN re-entry on restart)
        import secrets as _secrets
        secret = _secrets.token_hex(24)
    return hmac.HMAC(secret.encode(), pin.encode(), hashlib.sha256).hexdigest()


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
    """Return True if the PIN indicates open-access mode (empty string only)."""
    return not pin


def _validate_origin() -> bool:
    """Validate Origin header on state-changing requests.

    Returns True if the request is safe (same-origin or non-browser).
    Returns False if Origin header is present and does not match Host.
    """
    if request.method not in _STATE_CHANGING_METHODS:
        return True

    origin = request.headers.get("Origin")
    if not origin:
        # No Origin header — likely not a browser request, or same-origin
        # form submission. Allow (Referer check is defense-in-depth but
        # Origin is the primary CSRF defense with SameSite=Strict).
        return True

    # Extract host from Origin (scheme://host[:port])
    # Compare against request Host header
    host = request.host  # includes port if non-standard
    # Origin format: "http://hostname:port" or "https://hostname:port"
    try:
        origin_host = origin.split("://", 1)[1] if "://" in origin else origin
    except IndexError:
        log.warning("Malformed Origin header: %s", origin)
        return False

    if origin_host == host:
        return True

    log.warning(
        "Origin mismatch: Origin=%s, Host=%s, IP=%s, Path=%s",
        origin, host, request.remote_addr, request.path,
    )
    return False


def generate_pin(length: int = 4) -> str:
    """Generate a random numeric PIN of the given length."""
    if length == 6:
        return str(secrets.randbelow(900000) + 100000)
    return str(secrets.randbelow(9000) + 1000)


def rotate_pin_on_boot():
    """Rotate the PIN if PIN_ROTATE_ON_BOOT is enabled.

    Called once during app startup. Generates a new PIN and saves it.
    """
    if config.get("PIN_ROTATE_ON_BOOT", "no").lower() not in ("yes", "true", "1"):
        return

    pin_length = _get_pin_length()
    new_pin = generate_pin(pin_length)
    config.save({"ACCESS_PIN": new_pin})
    config.reload()
    log.warning("PIN rotated on boot (PIN_ROTATE_ON_BOOT=yes) — new PIN shown on TV")


def require_pin(func):
    """Decorator: require a valid framecast_pin cookie.

    Open access (no PIN or PIN == "0000") bypasses auth entirely.
    Paths on the skip list bypass auth.
    State-changing requests are validated against the Origin header.
    Otherwise, the cookie must match the stored ACCESS_PIN.
    Returns 401 JSON with ``needs_pin: true`` on failure.
    """

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        if _should_skip_auth():
            return func(*args, **kwargs)

        # Origin header validation on state-changing requests
        if not _validate_origin():
            log.warning(
                "Blocked cross-origin %s %s from %s",
                request.method, request.path, request.remote_addr,
            )
            return jsonify({"error": "ORIGIN MISMATCH"}), 403

        pin = _get_access_pin()
        if _pin_is_open_access(pin):
            return func(*args, **kwargs)

        cookie = request.cookies.get(COOKIE_NAME, "")
        if cookie and hmac.compare_digest(cookie, _make_auth_token(pin)):
            return func(*args, **kwargs)

        return jsonify({"error": "PIN required", "needs_pin": True}), 401

    return decorated


# --- Auth verification endpoint ---


@auth_api.route("/verify", methods=["POST"])
def verify_pin():
    """Validate a PIN and set an auth cookie on success.

    Accepts JSON: ``{"pin": "1234"}``.
    Returns 200 with cookie on match, 401 on mismatch.
    Rate limited: 5 attempts for 4-digit PIN, 3 attempts for 6-digit.
    5-minute lockout after exceeding max attempts.
    """
    # --- Rate limiting ---
    client_ip = request.remote_addr or "unknown"
    limiter = _get_pin_limiter()

    retry_after = limiter.check(client_ip)
    if retry_after is not None:
        log.warning("Rate limited PIN attempt from %s (%ds remaining)", client_ip, retry_after)
        return jsonify({"error": "TOO MANY ATTEMPTS — TRY AGAIN LATER", "retry_after": retry_after}), 429

    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("pin"), str):
        return jsonify({"error": "Missing or invalid pin field"}), 400

    submitted = data["pin"].strip()
    stored = _get_access_pin()

    if _pin_is_open_access(stored):
        # No PIN configured -- succeed immediately, no cookie needed
        return jsonify({"status": "ok", "message": "AUTHORIZED -- open access"})

    if not hmac.compare_digest(submitted, stored):
        log.warning(
            "PIN verification FAILED from %s",
            client_ip,
        )
        return jsonify({"error": "ACCESS DENIED", "needs_pin": True}), 401

    # Success — reset failure count
    limiter.reset(client_ip)

    log.warning("PIN verified successfully from %s", client_ip)
    resp = make_response(jsonify({"status": "ok", "message": "AUTHORIZED"}))

    # Detect HTTPS for Secure flag
    is_secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"

    resp.set_cookie(
        COOKIE_NAME,
        value=_make_auth_token(stored),
        max_age=COOKIE_MAX_AGE,
        samesite="Strict",
        httponly=True,
        secure=is_secure,
    )
    return resp
