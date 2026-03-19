"""JSON API blueprint for FrameCast.

Provides endpoints for the SPA frontend to list photos, get status,
read/write settings, and retrieve GPS locations.
"""

import logging
from pathlib import Path

from flask import Blueprint, jsonify, request

from modules import config, media

log = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

SCRIPT_DIR = Path(__file__).parent
VERSION_FILE = SCRIPT_DIR.parent / "VERSION"


def _read_version():
    """Read version string from VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _current_settings():
    """Build the current settings dict from config."""
    return {
        "photo_duration": int(config.get("PHOTO_DURATION", "10")),
        "shuffle": config.get("SHUFFLE", "yes").lower() == "yes",
        "transition_type": config.get("TRANSITION_TYPE", "fade"),
        "photo_order": config.get("PHOTO_ORDER", "shuffle"),
        "qr_display_seconds": int(config.get("QR_DISPLAY_SECONDS", "30")),
        "hdmi_schedule_enabled": config.get("HDMI_SCHEDULE_ENABLED", "no").lower() == "yes",
        "hdmi_off_time": config.get("HDMI_OFF_TIME", "22:00"),
        "hdmi_on_time": config.get("HDMI_ON_TIME", "08:00"),
        "max_upload_mb": int(config.get("MAX_UPLOAD_MB", "200")),
        "auto_resize_max": int(config.get("AUTO_RESIZE_MAX", "1920")),
        "auto_update_enabled": config.get("AUTO_UPDATE_ENABLED", "no").lower() == "yes",
        "web_port": int(config.get("WEB_PORT", "8080")),
    }


# Settings keys that map to .env keys with their type converters
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
    "web_port": ("WEB_PORT", str),
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
    })


@api.route("/settings")
def get_settings():
    """Return current settings dict."""
    return jsonify(_current_settings())


@api.route("/settings", methods=["POST"])
def update_settings():
    """Update settings from JSON body. Expects {"key": value, ...}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

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

    return jsonify({"status": "ok", "settings": _current_settings()})


@api.route("/locations")
def locations():
    """Return GPS locations for all photos as JSON."""
    locs = media.get_photo_locations()
    return jsonify(locs)
