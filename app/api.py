"""JSON API blueprint for FrameCast.

Provides endpoints for the SPA frontend to list photos, get status,
read/write settings, and retrieve GPS locations.
"""

import logging
import re
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

import sse
from modules import config, media, updater, wifi
from modules.auth import require_pin

log = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

SCRIPT_DIR = Path(__file__).parent
VERSION_FILE = SCRIPT_DIR.parent / "VERSION"

# Allowed enum values for constrained settings
_VALID_TRANSITION_TYPES = {"fade", "slide", "zoom", "dissolve", "none"}
_VALID_PHOTO_ORDERS = {"shuffle", "newest", "oldest", "alphabetical"}
_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _read_version():
    """Read version string from VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _safe_int(val, default):
    """Convert *val* to int, returning *default* on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _current_settings():
    """Build the current settings dict from config."""
    return {
        "photo_duration": _safe_int(config.get("PHOTO_DURATION", "10"), 10),
        "shuffle": config.get("SHUFFLE", "yes").lower() == "yes",
        "transition_type": config.get("TRANSITION_TYPE", "fade"),
        "photo_order": config.get("PHOTO_ORDER", "shuffle"),
        "qr_display_seconds": _safe_int(config.get("QR_DISPLAY_SECONDS", "30"), 30),
        "hdmi_schedule_enabled": config.get("HDMI_SCHEDULE_ENABLED", "no").lower() == "yes",
        "hdmi_off_time": config.get("HDMI_OFF_TIME", "22:00"),
        "hdmi_on_time": config.get("HDMI_ON_TIME", "08:00"),
        "max_upload_mb": _safe_int(config.get("MAX_UPLOAD_MB", "200"), 200),
        "auto_resize_max": _safe_int(config.get("AUTO_RESIZE_MAX", "1920"), 1920),
        "auto_update_enabled": config.get("AUTO_UPDATE_ENABLED", "no").lower() == "yes",
        "web_port": _safe_int(config.get("WEB_PORT", "8080"), 8080),
    }


# Settings keys that map to .env keys with their type converters.
# web_port is intentionally excluded — changing it via API could lock users out.
_SETTINGS_ENV_MAP = {
    "photo_duration": ("PHOTO_DURATION", str),
    "shuffle": ("SHUFFLE", lambda v: "yes" if v else "no"),
    "transition_type": ("TRANSITION_TYPE", str),
    "photo_order": ("PHOTO_ORDER", str),
    "qr_display_seconds": ("QR_DISPLAY_SECONDS", str),
    "hdmi_schedule_enabled": ("HDMI_SCHEDULE_ENABLED", lambda v: "yes" if v else "no"),
    "hdmi_off_time": ("HDMI_OFF_TIME", str),
    "hdmi_on_time": ("HDMI_ON_TIME", str),
    "max_upload_mb": ("MAX_UPLOAD_MB", str),
    "auto_resize_max": ("AUTO_RESIZE_MAX", str),
    "auto_update_enabled": ("AUTO_UPDATE_ENABLED", lambda v: "yes" if v else "no"),
}


@api.route("/photos")
def list_photos():
    """Return all media files as JSON."""
    files = media.get_media_files()
    return jsonify(files)


@api.route("/status")
def status():
    """Return system status: disk usage, counts, version, settings."""
    files = media.get_media_files()
    disk = media.get_disk_usage()
    return jsonify({
        "photo_count": sum(1 for f in files if not f["is_video"]),
        "video_count": sum(1 for f in files if f["is_video"]),
        "disk": disk,
        "version": _read_version(),
        "settings": _current_settings(),
        "access_pin": config.get("ACCESS_PIN", "").strip(),
    })


@api.route("/settings")
def get_settings():
    """Return current settings dict."""
    return jsonify(_current_settings())


@api.route("/settings", methods=["POST"])
@require_pin
def update_settings():
    """Update settings from JSON body. Expects {"key": value, ...}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    # --- Validate before touching config ---

    # Numeric fields must be positive integers
    for key in ("photo_duration", "qr_display_seconds", "max_upload_mb", "auto_resize_max"):
        if key in data:
            try:
                val = int(data[key])
                if val < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid value for {key}: must be a positive integer"}), 400

    # Time fields must be HH:MM (00:00–23:59)
    for key in ("hdmi_off_time", "hdmi_on_time"):
        if key in data:
            if not isinstance(data[key], str) or not _HH_MM_RE.match(data[key]):
                return jsonify({"error": f"Invalid value for {key}: must be HH:MM (00:00–23:59)"}), 400

    # Enum fields
    if "transition_type" in data and data["transition_type"] not in _VALID_TRANSITION_TYPES:
        return jsonify({
            "error": f"Invalid transition_type: must be one of {sorted(_VALID_TRANSITION_TYPES)}",
        }), 400

    if "photo_order" in data and data["photo_order"] not in _VALID_PHOTO_ORDERS:
        return jsonify({
            "error": f"Invalid photo_order: must be one of {sorted(_VALID_PHOTO_ORDERS)}",
        }), 400

    # --- Build update map ---

    updates = {}
    for key, value in data.items():
        if key in _SETTINGS_ENV_MAP:
            env_key, converter = _SETTINGS_ENV_MAP[key]
            updates[env_key] = converter(value)

    if not updates:
        return jsonify({"error": "No valid settings provided"}), 400

    config.save(updates)
    config.reload()
    log.info("Settings updated via API: %s", list(updates.keys()))
    sse.notify("settings:changed", _current_settings())

    return jsonify({"status": "ok", "settings": _current_settings()})


@api.route("/events")
def events():
    """SSE endpoint for real-time event streaming."""
    return Response(
        sse.subscribe(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api.route("/locations")
def locations():
    """Return GPS locations for all photos as JSON."""
    locs = media.get_photo_locations()
    return jsonify(locs)


# ---------------------------------------------------------------------------
# WiFi endpoints
# ---------------------------------------------------------------------------


@api.route("/wifi/status")
def wifi_status():
    """Return WiFi connection status, current SSID, AP state, and AP SSID."""
    return jsonify({
        "connected": wifi.is_connected(),
        "ssid": wifi.get_current_ssid(),
        "ap_active": wifi.is_ap_active(),
        "ap_ssid": wifi.get_ap_ssid(),
    })


@api.route("/wifi/scan")
def wifi_scan():
    """Scan for available WiFi networks with signal strength."""
    networks = wifi.scan_networks()
    return jsonify(networks)


@api.route("/wifi/connect", methods=["POST"])
@require_pin
def wifi_connect():
    """Connect to a WiFi network. Body: {"ssid": "...", "password": "..."}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    ssid = data.get("ssid", "").strip()
    password = data.get("password", "")

    if not ssid:
        return jsonify({"error": "SSID is required"}), 400

    success, message = wifi.connect(ssid, password)
    status_code = 200 if success else 502
    return jsonify({"success": success, "message": message}), status_code


@api.route("/wifi/ap/start", methods=["POST"])
@require_pin
def wifi_ap_start():
    """Start WiFi AP mode."""
    success, message = wifi.start_ap()
    status_code = 200 if success else 502
    return jsonify({"success": success, "message": message}), status_code


@api.route("/wifi/ap/stop", methods=["POST"])
@require_pin
def wifi_ap_stop():
    """Stop WiFi AP mode."""
    success, message = wifi.stop_ap()
    status_code = 200 if success else 502
    return jsonify({"success": success, "message": message}), status_code


# ---------------------------------------------------------------------------
# OTA Update endpoints
# ---------------------------------------------------------------------------


@api.route("/update/check", methods=["POST"])
@require_pin
def check_update():
    """Check GitHub for a newer version."""
    result = updater.check_for_update()
    return jsonify(result)


@api.route("/update/apply", methods=["POST"])
@require_pin
def apply_update():
    """Apply the specified update tag. Reboots on success."""
    data = request.get_json(silent=True) or {}
    tag = data.get("tag")
    if not tag:
        return jsonify({"error": "No tag specified"}), 400

    success, message = updater.apply_update(tag)
    if success:
        sse.notify("update:rebooting", {"version": tag})
        # Schedule reboot in 5 seconds (let the HTTP response return first)
        threading.Timer(5.0, lambda: subprocess.run(["sudo", "reboot"])).start()

    return jsonify({"success": success, "message": message})
