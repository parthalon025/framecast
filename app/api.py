"""JSON API blueprint for FrameCast.

Provides endpoints for the SPA frontend to list photos, get status,
read/write settings, retrieve GPS locations, and manage albums/tags/users.

Includes per-IP rate limiting (60 requests/minute) on state-changing API endpoints.
"""

import logging
import os
import re
import socket
import subprocess
import threading
from contextlib import closing
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request, send_file

import sse
from modules import cec, config, db, media, updater, users, wifi
from modules.auth import require_pin
from modules.rate_limiter import RateLimiter

log = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")


def _require_json():
    """Parse and validate JSON request body. Returns dict or aborts 400."""
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        abort(400, description="Invalid JSON body")
    return data


def _enrich_photos(photos):
    """Add name and size_human fields to photo dicts for frontend."""
    for photo in photos:
        photo["name"] = photo["filename"]
        photo["size_human"] = media.format_size(photo.get("file_size") or 0)
    return photos

# ---------------------------------------------------------------------------
# API rate limiting — 60 requests/minute per IP
# ---------------------------------------------------------------------------

_api_limiter = RateLimiter(max_attempts=60, window_seconds=60, evict_after=180)


@api.before_request
def _api_rate_limit():
    """Enforce per-IP rate limiting on state-changing /api/ endpoints."""
    # SSE endpoint is long-lived — exempt from rate limiting
    if request.path == "/api/events":
        return None
    # Only rate-limit state-changing requests; GETs are read-only
    if request.method == "GET":
        return None

    client_ip = request.remote_addr or "unknown"
    retry_after = _api_limiter.check(client_ip)
    if retry_after is not None:
        log.warning(
            "API rate limited: %s %s from %s",
            request.method, request.path, client_ip,
        )
        return jsonify({
            "error": "RATE LIMITED",
            "retry_after": retry_after,
        }), 429


def _do_reboot():
    """Execute a reboot, logging any failures instead of swallowing them."""
    try:
        result = subprocess.run(["sudo", "reboot"], capture_output=True, timeout=10)
        if result.returncode != 0:
            log.error("reboot failed (rc=%d): %s", result.returncode, result.stderr)
    except Exception:
        log.error("reboot subprocess raised", exc_info=True)


def _do_shutdown():
    """Execute a shutdown, logging any failures instead of swallowing them."""
    try:
        result = subprocess.run(["sudo", "shutdown", "-h", "now"], capture_output=True, timeout=10)
        if result.returncode != 0:
            log.error("shutdown failed (rc=%d): %s", result.returncode, result.stderr)
    except Exception:
        log.error("shutdown subprocess raised", exc_info=True)

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
        "transition_mode": config.get("TRANSITION_MODE", "single"),
        "transition_duration_ms": _safe_int(config.get("TRANSITION_DURATION_MS", "1000"), 1000),
        "kenburns_intensity": config.get("KENBURNS_INTENSITY", "moderate"),
        "photo_order": config.get("PHOTO_ORDER", "shuffle"),
        "qr_display_seconds": _safe_int(config.get("QR_DISPLAY_SECONDS", "30"), 30),
        "hdmi_schedule_enabled": config.get("HDMI_SCHEDULE_ENABLED", "no").lower() == "yes",
        "hdmi_off_time": config.get("HDMI_OFF_TIME", "22:00"),
        "hdmi_on_time": config.get("HDMI_ON_TIME", "08:00"),
        "schedule_days": config.get("DISPLAY_SCHEDULE_DAYS", "0,1,2,3,4,5,6"),
        "max_upload_mb": _safe_int(config.get("MAX_UPLOAD_MB", "200"), 200),
        "auto_resize_max": _safe_int(config.get("AUTO_RESIZE_MAX", "1920"), 1920),
        "auto_update_enabled": config.get("AUTO_UPDATE_ENABLED", "no").lower() == "yes",
        "pin_length": _safe_int(config.get("PIN_LENGTH", "4"), 4),
        "max_video_duration": _safe_int(config.get("MAX_VIDEO_DURATION", "30"), 30),
        "web_port": _safe_int(config.get("WEB_PORT", "8080"), 8080),
    }


# Settings keys that map to .env keys with their type converters.
# web_port is intentionally excluded — changing it via API could lock users out.
_VALID_TRANSITION_MODES = {"single", "random"}
_VALID_KENBURNS_INTENSITIES = {"subtle", "moderate", "dramatic"}
_VALID_PIN_LENGTHS = {4, 6}

_SETTINGS_ENV_MAP = {
    "photo_duration": ("PHOTO_DURATION", str),
    "shuffle": ("SHUFFLE", lambda v: "yes" if v else "no"),
    "transition_type": ("TRANSITION_TYPE", str),
    "transition_mode": ("TRANSITION_MODE", str),
    "transition_duration_ms": ("TRANSITION_DURATION_MS", str),
    "kenburns_intensity": ("KENBURNS_INTENSITY", str),
    "photo_order": ("PHOTO_ORDER", str),
    "qr_display_seconds": ("QR_DISPLAY_SECONDS", str),
    "hdmi_schedule_enabled": ("HDMI_SCHEDULE_ENABLED", lambda v: "yes" if v else "no"),
    "hdmi_off_time": ("HDMI_OFF_TIME", str),
    "hdmi_on_time": ("HDMI_ON_TIME", str),
    "schedule_days": ("DISPLAY_SCHEDULE_DAYS", str),
    "max_upload_mb": ("MAX_UPLOAD_MB", str),
    "auto_resize_max": ("AUTO_RESIZE_MAX", str),
    "auto_update_enabled": ("AUTO_UPDATE_ENABLED", lambda v: "yes" if v else "no"),
    "pin_length": ("PIN_LENGTH", str),
    "max_video_duration": ("MAX_VIDEO_DURATION", str),
}


@api.route("/photos")
def list_photos():
    """Return media files as JSON from database.

    Query params:
        filter: 'favorites' | 'hidden' | omit for default (non-hidden, non-quarantined)
    """
    try:
        photo_filter = request.args.get("filter", "")
        favorite_only = photo_filter == "favorites"
        include_hidden = photo_filter == "hidden"

        photos = db.get_photos(
            favorite_only=favorite_only,
            include_hidden=include_hidden,
        )
        _enrich_photos(photos)
        return jsonify(photos)
    except Exception:
        log.warning("DB query failed for /api/photos, falling back to filesystem", exc_info=True)
        files = media.get_media_files()
        return jsonify(files)


@api.route("/search")
def search_photos_endpoint():
    """Search photos by filename, tags, or album names."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"photos": [], "query": ""})
    photos = db.search_photos(q)
    return jsonify({"photos": _enrich_photos(photos), "query": q})


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
        "hostname": socket.gethostname(),
        "settings": _current_settings(),
    }
    # Only expose PIN to localhost (TV display needs it to show on-screen)
    if request.remote_addr in ("127.0.0.1", "::1"):
        result["access_pin"] = config.get("ACCESS_PIN", "").strip()
    return jsonify(result)


@api.route("/hostname")
def get_hostname():
    """Return the current system hostname."""
    return jsonify({"hostname": socket.gethostname()})


@api.route("/settings")
def get_settings():
    """Return current settings dict."""
    return jsonify(_current_settings())


@api.route("/settings", methods=["POST"])
@require_pin
def update_settings():
    """Update settings from JSON body. Expects {"key": value, ...}."""
    data = _require_json()

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

    if "transition_mode" in data and data["transition_mode"] not in _VALID_TRANSITION_MODES:
        return jsonify({
            "error": f"Invalid transition_mode: must be one of {sorted(_VALID_TRANSITION_MODES)}",
        }), 400

    if "kenburns_intensity" in data and data["kenburns_intensity"] not in _VALID_KENBURNS_INTENSITIES:
        return jsonify({
            "error": f"Invalid kenburns_intensity: must be one of {sorted(_VALID_KENBURNS_INTENSITIES)}",
        }), 400

    if "transition_duration_ms" in data:
        try:
            val = int(data["transition_duration_ms"])
            if val < 500 or val > 3000:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid transition_duration_ms: must be 500-3000"}), 400

    if "max_video_duration" in data:
        try:
            val = int(data["max_video_duration"])
            if not (5 <= val <= 300):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid max_video_duration: must be 5-300"}), 400

    if "pin_length" in data:
        try:
            val = int(data["pin_length"])
            if val not in _VALID_PIN_LENGTHS:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid pin_length: must be 4 or 6"}), 400

    if "schedule_days" in data:
        if not re.match(r'^[0-6](,[0-6])*$', str(data["schedule_days"])):
            return jsonify({"error": f"Invalid schedule_days: {data['schedule_days']}"}), 400

    # --- Handle action keys (not persistent settings) ---

    # display_on is a toggle action, not a persistent setting
    if "display_on" in data:
        from modules import cec
        if data["display_on"]:
            cec.tv_power_on()
            cec.set_active_source()
        else:
            cec.tv_standby()
        # Remove from data so it doesn't hit _SETTINGS_ENV_MAP
        data = {k: v for k, v in data.items() if k != "display_on"}

    # regenerate_pin is an action, not a setting
    if "regenerate_pin" in data:
        from modules.auth import generate_pin
        pin_length = int(data.get("pin_length", config.get("PIN_LENGTH", "4")))
        if pin_length not in (4, 6):
            pin_length = 4
        new_pin = generate_pin(pin_length)
        config.save({"ACCESS_PIN": new_pin})
        config.reload()
        log.info("PIN regenerated via settings API")
        data = {k: v for k, v in data.items() if k != "regenerate_pin"}

    # --- Build update map ---

    updates = {}
    for key, value in data.items():
        if key in _SETTINGS_ENV_MAP:
            env_key, converter = _SETTINGS_ENV_MAP[key]
            updates[env_key] = converter(value)

    if updates:
        config.save(updates)
        config.reload()
        log.info("Settings updated via API: %s", list(updates.keys()))
        sse.notify("settings:changed", _current_settings())
    elif not data:
        # No settings and no action keys were processed
        return jsonify({"error": "No valid settings provided"}), 400

    return jsonify({"status": "ok", "settings": _current_settings()})


@api.route("/settings/export")
@require_pin
def export_settings():
    """Export current settings as JSON."""
    settings = _current_settings()
    return jsonify(settings)


@api.route("/settings/import", methods=["POST"])
@require_pin
def import_settings():
    """Import settings from JSON. Validates keys before applying."""
    data = _require_json()
    # Only allow known settings keys
    allowed = set(_SETTINGS_ENV_MAP.keys())
    filtered = {k: v for k, v in data.items() if k in allowed}
    if not filtered:
        return jsonify({"error": "No valid settings found"}), 400
    # Apply through normal settings update path
    env_updates = {}
    for key, val in filtered.items():
        env_key, converter = _SETTINGS_ENV_MAP[key]
        env_updates[env_key] = converter(val)
    config.save(env_updates)
    config.reload()
    sse.notify("settings:changed", _current_settings())
    return jsonify({"status": "ok", "imported": len(filtered), "keys": list(filtered.keys())})


@api.route("/timezone", methods=["POST"])
@require_pin
def set_timezone():
    """Set the system timezone via timedatectl."""
    data = _require_json()
    tz = data.get("timezone", "").strip()
    if not tz or "/" not in tz:
        return jsonify({"error": "Invalid timezone format"}), 400
    try:
        result = subprocess.run(
            ["timedatectl", "set-timezone", tz],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            log.error("timedatectl failed: %s", result.stderr)
            return jsonify({"error": f"Invalid timezone: {tz}"}), 400
    except Exception as exc:
        log.error("Failed to set timezone: %s", exc)
        return jsonify({"error": "Failed to set timezone"}), 500
    log.info("Timezone set to %s", tz)
    return jsonify({"status": "ok", "timezone": tz})


@api.route("/timezone")
def get_timezone():
    """Get the current system timezone."""
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        tz = result.stdout.strip() or "UTC"
    except Exception:
        log.error("Failed to read timezone", exc_info=True)
        tz = "UTC"
    return jsonify({"timezone": tz})


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
# Guest upload links (Issue #44)
# ---------------------------------------------------------------------------


@api.route("/guest/create", methods=["POST"])
@require_pin
def create_guest_link():
    """Generate a time-limited guest upload token.

    Requires PIN auth (only the frame owner can create guest links).
    Body (optional): ``{"ttl_hours": 24}`` — clamped to 1h–168h (7d).
    """
    from modules.auth import generate_guest_token

    data = request.get_json(silent=True) or {}
    try:
        ttl = int(data.get("ttl_hours", 24))
    except (TypeError, ValueError):
        ttl = 24
    ttl = min(max(ttl, 1), 168)  # 1h to 7d
    token = generate_guest_token(ttl)
    log.info("Guest upload link created (TTL=%dh) by %s", ttl, request.remote_addr)
    return jsonify({"token": token, "ttl_hours": ttl})


@api.route("/guest/validate")
def validate_guest():
    """Check if a guest token is valid (unauthenticated — used by the SPA)."""
    from modules.auth import validate_guest_token

    token = request.args.get("token", "")
    return jsonify({"valid": validate_guest_token(token)})


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
    sse.notify("photo:favorited", {"id": photo_id, "is_favorite": new_val})
    return jsonify({"status": "ok", "photo_id": photo_id, "is_favorite": new_val})


@api.route("/photos/<int:photo_id>/quarantine", methods=["POST"])
def quarantine_photo(photo_id):
    """Quarantine a photo (localhost only — called from TV display)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "LOCALHOST ONLY"}), 403

    photo = db.get_photo_by_id(photo_id)
    if not photo:
        return jsonify({"error": "Photo not found"}), 404

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "auto-quarantined")
    db.update_photo_quarantine(photo_id, True, reason)
    log.info("Photo %d quarantined: %s", photo_id, reason)
    return jsonify({"status": "ok", "photo_id": photo_id})


@api.route("/photos/<int:photo_id>/duplicates")
def photo_duplicates(photo_id):
    """Find near-duplicate photos by perceptual hash."""
    photo = db.get_photo_by_id(photo_id)
    if not photo:
        abort(404)
    if not photo["dhash"]:
        return jsonify({"duplicates": [], "message": "No perceptual hash available"})
    dupes = db.find_near_duplicates(photo["dhash"])
    # Exclude self
    dupes = [d for d in dupes if d["id"] != photo_id]
    return jsonify({"duplicates": _enrich_photos(dupes)})


# ---------------------------------------------------------------------------
# Batch photo actions
# ---------------------------------------------------------------------------


@api.route("/photos/batch/delete", methods=["POST"])
@require_pin
def batch_delete_photos():
    """Delete multiple photos by ID (quarantine)."""
    data = _require_json()
    ids = data.get("ids", [])
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "ids required"}), 400
    deleted = 0
    for pid in ids[:100]:  # Cap at 100
        try:
            db.update_photo_quarantine(int(pid), True, "batch delete")
            deleted += 1
        except Exception as exc:
            log.warning("Batch delete failed for %d: %s", pid, exc)
    sse.notify("photo:deleted", {"count": deleted})
    return jsonify({"status": "ok", "deleted": deleted})


@api.route("/photos/batch/favorite", methods=["POST"])
@require_pin
def batch_favorite_photos():
    """Toggle favorite on multiple photos."""
    data = _require_json()
    ids = data.get("ids", [])
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "ids required"}), 400
    toggled = 0
    for pid in ids[:100]:
        try:
            db.toggle_favorite(int(pid))
            toggled += 1
        except Exception as exc:
            log.warning("Batch favorite failed for %d: %s", pid, exc)
    return jsonify({"status": "ok", "toggled": toggled})


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
        first = photos[0] if photos else None
        result.append({
            "id": f"smart:{key}",
            "name": album_def["name"],
            "description": None,
            "cover_photo_id": first["id"] if first else None,
            "cover_filename": first["filename"] if first else None,
            "photo_count": len(photos),
            "smart": True,
        })

    return jsonify(result)


@api.route("/albums", methods=["POST"])
@require_pin
def create_album():
    """Create a new album. Body: {"name": "...", "description": "..."}."""
    data = _require_json()

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


@api.route("/albums/<int:album_id>/photos")
def list_album_photos(album_id):
    """Return all photos in an album."""
    photos = db.get_album_photos(album_id)
    _enrich_photos(photos)
    return jsonify(photos)


@api.route("/albums/smart/<smart_key>/photos")
def list_smart_album_photos(smart_key):
    """Return photos matching a smart album query."""
    photos = db.get_smart_album_photos(smart_key)
    _enrich_photos(photos)
    return jsonify(photos)


@api.route("/albums/<int:album_id>/photos", methods=["POST"])
@require_pin
def add_photo_to_album(album_id):
    """Add a photo to an album. Body: {"photo_id": int}."""
    data = _require_json()

    try:
        photo_id = int(data.get("photo_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "photo_id must be an integer"}), 400
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


@api.route("/tags")
def list_all_tags():
    """Return all tags for autocomplete."""
    tags = db.get_all_tags()
    return jsonify(tags)


@api.route("/photos/<int:photo_id>/tags")
def list_photo_tags(photo_id):
    """Return all tags for a photo."""
    tags = db.get_tags(photo_id)
    return jsonify(tags)


@api.route("/photos/<int:photo_id>/tags", methods=["POST"])
@require_pin
def add_photo_tag(photo_id):
    """Add a tag to a photo. Body: {"name": "..."}."""
    data = _require_json()

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


@api.route("/slideshow/now-playing", methods=["POST"])
def slideshow_now_playing():
    """Called by the TV display when the slideshow advances.

    Broadcasts the current photo to phone clients via SSE so the phone
    can show a "now playing" indicator.
    """
    data = request.get_json(silent=True) or {}
    sse.notify("slideshow:now_playing", {
        "photo_id": data.get("photo_id"),
        "filename": data.get("filename"),
    })
    return jsonify({"status": "ok"})


@api.route("/slideshow/show/<int:photo_id>", methods=["POST"])
@require_pin
def slideshow_show_photo(photo_id):
    """Tell the TV slideshow to immediately display a specific photo."""
    photo = db.get_photo_by_id(photo_id)
    if not photo:
        abort(404)
    sse.notify("slideshow:show", {
        "photo_id": photo["id"],
        "filename": photo["filename"],
        "filepath": photo["filepath"],
        "is_video": bool(photo["is_video"]),
    })
    return jsonify({"status": "ok", "photo_id": photo_id})


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
# Display control (HDMI-CEC) endpoints
# ---------------------------------------------------------------------------


@api.route("/display/on", methods=["POST"])
@require_pin
def display_on():
    """Power on TV via CEC."""
    success = cec.tv_power_on()
    if success:
        cec.set_active_source()
    return jsonify({"success": success, "power": "on" if success else "unknown"})


@api.route("/display/off", methods=["POST"])
@require_pin
def display_off():
    """Put TV into standby via CEC."""
    success = cec.tv_standby()
    return jsonify({"success": success, "power": "standby" if success else "unknown"})


@api.route("/display/status")
def display_status():
    """Query TV power status via CEC."""
    power = cec.tv_status()
    return jsonify({"power": power})


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


@api.route("/stats")
def get_stats():
    """Return aggregated content and display statistics (full dashboard data)."""
    try:
        stats = users.get_full_stats()
    except Exception:
        log.warning("Full stats failed, falling back to basic stats", exc_info=True)
        stats = db.get_stats()
    return jsonify(stats)


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@api.route("/users")
def list_users():
    """Return all users ordered by upload count."""
    user_list = users.get_users()
    return jsonify(user_list)


@api.route("/users", methods=["POST"])
@require_pin
def create_user():
    """Create a new user. Body: {"name": "..."}."""
    data = _require_json()

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "User name is required"}), 400

    try:
        user_row = users.create_user(name)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            return jsonify({"error": "User name already exists"}), 409
        log.error("Failed to create user: %s", exc)
        return jsonify({"error": "Failed to create user"}), 500

    log.info("User created: %s", name)
    return jsonify({"status": "ok", "user": user_row}), 201


@api.route("/users/<int:user_id>", methods=["DELETE"])
@require_pin
def delete_user(user_id):
    """Delete a user by id. Reassigns their photos to 'default'."""
    try:
        users.delete_user(user_id)
    except Exception as exc:
        log.error("Failed to delete user %d: %s", user_id, exc)
        return jsonify({"error": "Failed to delete user"}), 500
    return jsonify({"status": "ok"})


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


@api.route("/restore", methods=["POST"])
@require_pin
def restore_backup():
    """Restore database from an uploaded backup file.

    Expects multipart form upload with field name 'backup'.
    Validates the uploaded file is a valid SQLite DB with required tables.
    """
    if "backup" not in request.files:
        return jsonify({"error": "No backup file provided"}), 400

    uploaded = request.files["backup"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Save to temp file for validation
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)

    try:
        uploaded.save(tmp_path)

        # Validate and restore
        db.restore_db(tmp_path)

        return jsonify({
            "status": "ok",
            "message": "Database restored. Restart recommended.",
        })
    except ValueError as exc:
        log.warning("Restore validation failed: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        log.error("Restore failed: %s", exc)
        return jsonify({"error": "Restore failed"}), 500
    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------


@api.route("/export")
@require_pin
def export_photos():
    """Stream a zip archive of all non-quarantined photos.

    Writes to a temp file first to avoid OOM on Pi 3 with limited RAM.
    Uses ZIP_STORED (no compression) for lower CPU usage.
    """
    import tempfile
    import time
    import zipfile

    from flask import after_this_request

    media_dir = Path(media.get_media_dir())

    with closing(db.get_db()) as conn:
        photos = conn.execute(
            "SELECT filename, filepath FROM photos WHERE quarantined = 0"
        ).fetchall()

    if not photos:
        return jsonify({"error": "No photos to export"}), 404

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)

    @after_this_request
    def cleanup(response):
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        return response

    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
            for photo in photos:
                filepath = media_dir / photo["filepath"]
                if filepath.exists() and filepath.is_file():
                    zf.write(str(filepath), arcname=photo["filename"])

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        return send_file(
            tmp_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"framecast-export-{timestamp}.zip",
        )
    except Exception as exc:
        log.error("Export failed: %s", exc)
        return jsonify({"error": "Export failed"}), 500


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


@api.route("/wifi/test")
def wifi_test_connection():
    """Test internet connectivity by pinging a reliable host."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "3", "8.8.8.8"],
            capture_output=True, timeout=5,
        )
        online = result.returncode == 0
    except Exception:
        log.warning("WiFi connectivity test failed", exc_info=True)
        online = False
    return jsonify({"online": online})


@api.route("/wifi/connect", methods=["POST"])
@require_pin
def wifi_connect():
    """Connect to a WiFi network. Body: {"ssid": "...", "password": "..."}."""
    data = _require_json()

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
# SSH control endpoints (Issue #4)
# ---------------------------------------------------------------------------


@api.route("/ssh/status")
@require_pin
def ssh_status():
    """Check if SSH is enabled."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "ssh"],
            capture_output=True, text=True, timeout=5,
        )
        active = result.stdout.strip() == "active"
    except Exception:
        log.error("SSH status check failed", exc_info=True)
        active = False
    return jsonify({"enabled": active})


@api.route("/ssh/toggle", methods=["POST"])
@require_pin
def ssh_toggle():
    """Enable or disable SSH service."""
    data = _require_json()
    enable = data.get("enabled", False)
    try:
        if enable:
            subprocess.run(
                ["sudo", "systemctl", "enable", "--now", "ssh"],
                capture_output=True, timeout=10, check=True,
            )
            log.info("SSH enabled via web UI")
        else:
            subprocess.run(
                ["sudo", "systemctl", "disable", "--now", "ssh"],
                capture_output=True, timeout=10, check=True,
            )
            log.info("SSH disabled via web UI")
    except subprocess.CalledProcessError as exc:
        log.error("SSH toggle failed: %s", exc)
        return jsonify({"error": "Failed to toggle SSH"}), 500
    except Exception as exc:
        log.error("SSH toggle failed: %s", exc)
        return jsonify({"error": "Failed to toggle SSH"}), 500
    return jsonify({"status": "ok", "enabled": enable})


# ---------------------------------------------------------------------------
# HTTPS (self-signed certificate)
# ---------------------------------------------------------------------------


@api.route("/https/status")
@require_pin
def https_status():
    """Check HTTPS configuration status."""
    cert_dir = Path(media.get_media_dir()) / "certs"
    has_cert = (cert_dir / "server.crt").exists() and (cert_dir / "server.key").exists()
    enabled = config.get("HTTPS_ENABLED", "no").lower() == "yes"
    return jsonify({"has_cert": has_cert, "enabled": enabled})


@api.route("/https/toggle", methods=["POST"])
@require_pin
def https_toggle():
    """Enable or disable HTTPS. Generates cert if missing."""
    data = _require_json()
    enable = data.get("enabled", False)

    if enable:
        # Generate cert if missing
        cert_dir = Path(media.get_media_dir()) / "certs"
        if not (cert_dir / "server.crt").exists():
            try:
                subprocess.run(
                    [str(Path(__file__).parent.parent / "scripts" / "generate-cert.sh")],
                    env={**os.environ, "MEDIA_DIR": media.get_media_dir()},
                    capture_output=True, timeout=30, check=True,
                )
            except Exception as exc:
                log.error("Cert generation failed: %s", exc)
                return jsonify({"error": "Failed to generate certificate"}), 500

    config.save({"HTTPS_ENABLED": "yes" if enable else "no"})
    return jsonify({
        "status": "ok",
        "enabled": enable,
        "message": "Restart required for changes to take effect",
    })


# ---------------------------------------------------------------------------
# Frame discovery (mDNS / avahi)
# ---------------------------------------------------------------------------


@api.route("/frames")
def discover_frames():
    """Discover other FrameCast devices on the local network via mDNS."""
    frames = []
    try:
        result = subprocess.run(
            ["avahi-browse", "-tprk", "_http._tcp"],
            capture_output=True, text=True, timeout=5,
        )
        my_hostname = socket.gethostname()
        for line in result.stdout.splitlines():
            if not line.startswith("=") or "model=framecast" not in line:
                continue
            parts = line.split(";")
            if len(parts) < 8:
                continue
            hostname = parts[3]
            ip = parts[7]
            port = parts[8] if len(parts) > 8 else "8080"
            if hostname != my_hostname:
                frames.append({
                    "hostname": hostname,
                    "ip": ip,
                    "port": port,
                    "url": f"http://{ip}:{port}",
                })
    except FileNotFoundError:
        log.info("avahi-browse not found — frame discovery disabled")
    except subprocess.TimeoutExpired:
        log.warning("avahi-browse timed out during frame discovery")
    except Exception:
        log.warning("Frame discovery failed", exc_info=True)
    return jsonify({"frames": frames})


# ---------------------------------------------------------------------------
# System control endpoints (migrated from web_upload.py)
# ---------------------------------------------------------------------------


@api.route("/restart-slideshow", methods=["POST"])
@require_pin
def restart_slideshow():
    """Restart the slideshow service."""
    from modules import services
    success, message = services.restart_slideshow()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 500


@api.route("/reboot", methods=["POST"])
@require_pin
def api_reboot():
    """Reboot the device."""
    log.info("Reboot requested via web UI from %s", request.remote_addr)
    threading.Timer(0.5, _do_reboot).start()
    return jsonify({"status": "ok", "message": "Device is rebooting..."})


@api.route("/shutdown", methods=["POST"])
@require_pin
def api_shutdown():
    """Shut down the device."""
    log.info("Shutdown requested via web UI from %s", request.remote_addr)
    threading.Timer(0.5, _do_shutdown).start()
    return jsonify({"status": "ok", "message": "Device is shutting down..."})


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

    expected_sha = data.get("expected_sha", "")
    success, message = updater.apply_update(tag, expected_sha=expected_sha)
    if success:
        sse.notify("update:rebooting", {"version": tag})
        # Schedule reboot in 5 seconds (let the HTTP response return first)
        threading.Timer(5.0, _do_reboot).start()

    return jsonify({"success": success, "message": message})
