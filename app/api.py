"""JSON API blueprint for FrameCast.

Provides endpoints for the SPA frontend to list photos, get status,
read/write settings, retrieve GPS locations, and manage albums/tags/users.
"""

import logging
import re
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

import sse
from modules import config, db, media, updater, wifi
from modules.auth import require_pin

log = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")


def _do_reboot():
    """Execute a reboot, logging any failures instead of swallowing them."""
    try:
        result = subprocess.run(["sudo", "reboot"], capture_output=True, timeout=10)
        if result.returncode != 0:
            log.error("reboot failed (rc=%d): %s", result.returncode, result.stderr)
    except Exception:
        log.error("reboot subprocess raised", exc_info=True)

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
    """Return all media files as JSON from database."""
    try:
        photos = db.get_photos()
        # Augment with human-readable size for frontend compatibility
        for photo in photos:
            photo["name"] = photo["filename"]
            photo["size_human"] = media.format_size(photo.get("file_size") or 0)
        return jsonify(photos)
    except Exception:
        log.warning("DB query failed for /api/photos, falling back to filesystem", exc_info=True)
        files = media.get_media_files()
        return jsonify(files)


@api.route("/status")
def status():
    """Return system status: disk usage, counts, version, settings."""
    disk = media.get_disk_usage()
    try:
        stats = db.get_stats()
        photo_count = stats["total_photos"] - stats["videos"]
        video_count = stats["videos"]
    except Exception:
        log.warning("DB stats failed, falling back to filesystem", exc_info=True)
        files = media.get_media_files()
        photo_count = sum(1 for f in files if not f["is_video"])
        video_count = sum(1 for f in files if f["is_video"])

    result = {
        "photo_count": photo_count,
        "video_count": video_count,
        "disk": disk,
        "version": _read_version(),
        "settings": _current_settings(),
    }
    # Only expose PIN to localhost (TV display needs it to show on-screen)
    if request.remote_addr in ("127.0.0.1", "::1"):
        result["access_pin"] = config.get("ACCESS_PIN", "").strip()
    return jsonify(result)


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

    # Numeric fields must be positive integers (qr_display_seconds allows 0 = disable)
    for key in ("photo_duration", "max_upload_mb", "auto_resize_max"):
        if key in data:
            try:
                val = int(data[key])
                if val < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid value for {key}: must be a positive integer"}), 400

    # qr_display_seconds: 0 = disable, otherwise positive integer
    if "qr_display_seconds" in data:
        try:
            val = int(data["qr_display_seconds"])
            if val < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid value for qr_display_seconds: must be 0 or a positive integer"}), 400

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
    last_event_id = request.headers.get("Last-Event-ID")
    return Response(
        sse.subscribe(last_event_id=last_event_id),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api.route("/locations")
def locations():
    """Return GPS locations for all photos from database."""
    try:
        photos = db.get_photos()
        locs = [
            {"name": p["filename"], "lat": p["gps_lat"], "lon": p["gps_lon"]}
            for p in photos
            if p.get("gps_lat") is not None and p.get("gps_lon") is not None
        ]
        return jsonify(locs)
    except Exception:
        log.warning("DB query failed for /api/locations, falling back to cache", exc_info=True)
        locs = media.get_photo_locations()
        return jsonify(locs)


# ---------------------------------------------------------------------------
# Photo actions
# ---------------------------------------------------------------------------


@api.route("/photos/<int:photo_id>/favorite", methods=["POST"])
@require_pin
def toggle_photo_favorite(photo_id):
    """Toggle favorite status for a photo (atomic SQL)."""
    photo = db.get_photo_by_id(photo_id)
    if not photo:
        return jsonify({"error": "Photo not found"}), 404

    new_val = db.toggle_favorite(photo_id)
    status_label = "FAVORITE" if new_val else "UNFAVORITED"
    log.info("Photo %d: %s", photo_id, status_label)
    return jsonify({"status": "ok", "photo_id": photo_id, "is_favorite": new_val})


# ---------------------------------------------------------------------------
# Album endpoints
# ---------------------------------------------------------------------------


@api.route("/albums")
def list_albums():
    """Return all albums (regular + smart) as JSON."""
    albums = db.get_albums()
    result = [dict(a, smart=False) for a in albums]

    # Append smart albums
    for key, album_def in db.SMART_ALBUMS.items():
        photos = db.get_smart_album_photos(key)
        result.append({
            "id": f"smart:{key}",
            "name": album_def["name"],
            "description": None,
            "cover_photo_id": photos[0]["id"] if photos else None,
            "photo_count": len(photos),
            "smart": True,
        })

    return jsonify(result)


@api.route("/albums", methods=["POST"])
@require_pin
def create_album():
    """Create a new album. Body: {"name": "...", "description": "..."}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Album name is required"}), 400

    try:
        album_id = db.create_album(name, data.get("description"))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            return jsonify({"error": "Album name already exists"}), 409
        log.error("Failed to create album: %s", exc)
        return jsonify({"error": "Failed to create album"}), 500

    log.info("Album created: %s (id=%d)", name, album_id)
    return jsonify({"status": "ok", "album_id": album_id}), 201


@api.route("/albums/<int:album_id>", methods=["DELETE"])
@require_pin
def delete_album_endpoint(album_id):
    """Delete an album by id."""
    db.delete_album(album_id)
    log.info("Album deleted: id=%d", album_id)
    return jsonify({"status": "ok"})


@api.route("/albums/<int:album_id>/photos", methods=["POST"])
@require_pin
def add_photo_to_album(album_id):
    """Add a photo to an album. Body: {"photo_id": int}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    photo_id = data.get("photo_id")
    if not photo_id:
        return jsonify({"error": "photo_id is required"}), 400

    db.add_to_album(photo_id, album_id)
    return jsonify({"status": "ok"})


@api.route("/albums/<int:album_id>/photos/<int:photo_id>", methods=["DELETE"])
@require_pin
def remove_photo_from_album(album_id, photo_id):
    """Remove a photo from an album."""
    db.remove_from_album(photo_id, album_id)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Tag endpoints
# ---------------------------------------------------------------------------


@api.route("/photos/<int:photo_id>/tags")
def list_photo_tags(photo_id):
    """Return all tags for a photo."""
    tags = db.get_tags(photo_id)
    return jsonify(tags)


@api.route("/photos/<int:photo_id>/tags", methods=["POST"])
@require_pin
def add_photo_tag(photo_id):
    """Add a tag to a photo. Body: {"name": "..."}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Tag name is required"}), 400

    tag_id = db.add_tag(photo_id, name)
    return jsonify({"status": "ok", "tag_id": tag_id}), 201


@api.route("/photos/<int:photo_id>/tags/<int:tag_id>", methods=["DELETE"])
@require_pin
def remove_photo_tag(photo_id, tag_id):
    """Remove a tag from a photo."""
    db.remove_tag(photo_id, tag_id)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Slideshow playlist endpoint
# ---------------------------------------------------------------------------


@api.route("/slideshow/playlist")
def slideshow_playlist():
    """Return a weighted playlist of photos for the slideshow."""
    try:
        count = _safe_int(request.args.get("count"), 50)
        count = max(1, min(count, 200))  # clamp to reasonable range
        from modules import rotation
        result = rotation.generate_playlist(count=count)
        return jsonify(result)
    except Exception:
        log.error("Failed to generate slideshow playlist", exc_info=True)
        return jsonify({"photos": [], "playlist_id": "error"}), 500


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


@api.route("/stats")
def get_stats():
    """Return aggregated content and display statistics."""
    stats = db.get_stats()
    return jsonify(stats)


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@api.route("/users")
def list_users():
    """Return all users."""
    users = db.get_users()
    return jsonify(users)


@api.route("/users", methods=["POST"])
@require_pin
def create_user():
    """Create a new user. Body: {"name": "..."}."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "User name is required"}), 400

    try:
        user_id = db.create_user(name, is_admin=bool(data.get("is_admin")))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            return jsonify({"error": "User name already exists"}), 409
        log.error("Failed to create user: %s", exc)
        return jsonify({"error": "Failed to create user"}), 500

    log.info("User created: %s (id=%d)", name, user_id)
    return jsonify({"status": "ok", "user_id": user_id}), 201


# ---------------------------------------------------------------------------
# Backup endpoint
# ---------------------------------------------------------------------------


@api.route("/backup")
@require_pin
def download_backup():
    """Download a fresh database backup."""
    try:
        backup_path = db.backup_db()
        return send_file(
            backup_path,
            mimetype="application/x-sqlite3",
            as_attachment=True,
            download_name="framecast.db.backup",
        )
    except FileNotFoundError:
        return jsonify({"error": "Database not found"}), 404
    except Exception as exc:
        log.error("Backup failed: %s", exc)
        return jsonify({"error": "Backup failed"}), 500


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

    if not updater.validate_tag(tag):
        return jsonify({"error": f"Invalid tag format: {tag}"}), 400

    success, message = updater.apply_update(tag)
    if success:
        sse.notify("update:rebooting", {"version": tag})
        # Schedule reboot in 5 seconds (let the HTTP response return first)
        threading.Timer(5.0, _do_reboot).start()

    return jsonify({"success": success, "message": message})
