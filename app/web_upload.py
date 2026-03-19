#!/usr/bin/env python3
"""Web upload server for Pi Photo Display.

Provides a web interface to upload, manage, and configure the
Raspberry Pi photo/video slideshow over the local network.
"""

import functools
import logging
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from api import api
from modules import config, media, services

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# --- Self-healing .env ---


def _heal_env_file():
    """If .env is missing or empty, restore from .env.example and regenerate secrets.

    This prevents silent fallback to defaults which can cause subtle issues
    (wrong media directory, no secret key, etc.) after SD card corruption.
    """
    env_file = Path(__file__).parent / ".env"
    env_example = Path(__file__).parent / ".env.example"

    if env_file.exists() and env_file.stat().st_size > 10:
        return  # .env looks valid

    if not env_file.exists():
        log.critical(".env file missing at %s", env_file)
    else:
        log.critical(".env file is empty or corrupt at %s (size: %d bytes)", env_file, env_file.stat().st_size)

    if env_example.exists():
        log.warning("Self-healing: Restoring .env from .env.example")
        shutil.copy2(str(env_example), str(env_file))
        # Regenerate the secret key in the restored file
        new_secret = secrets.token_hex(24)
        config.save({"FLASK_SECRET_KEY": new_secret})
        config.reload()
        log.warning("Self-healing: .env restored with new secret key. Review settings.")
    else:
        log.critical("No .env.example found - cannot self-heal. Using built-in defaults.")


_heal_env_file()


# --- Config ---

SCRIPT_DIR = Path(__file__).parent
MEDIA_DIR = media.get_media_dir()
THUMBNAIL_DIR = str(Path(MEDIA_DIR) / "thumbnails")
PORT = int(config.get("WEB_PORT", "8080"))
MAX_UPLOAD_MB = int(config.get("MAX_UPLOAD_MB", "200"))
AUTO_RESIZE_MAX = int(config.get("AUTO_RESIZE_MAX", "1920"))
WEB_PASSWORD = config.get("WEB_PASSWORD", "").strip()

# Semaphore to limit concurrent uploads (Pi 3B has only 1GB RAM).
# A single large upload can use 200MB+; two simultaneous ones cause OOM.
_upload_semaphore = threading.Semaphore(2)

# --- MEDIA_DIR validation ---

def _validate_media_dir(media_dir):
    """Verify MEDIA_DIR is under a safe parent directory."""
    try:
        resolved = Path(media_dir).resolve()
        home_dir = Path.home().resolve()
        safe_prefixes = (home_dir, Path("/media").resolve(), Path("/mnt").resolve())
        if not any(resolved == prefix or str(resolved).startswith(str(prefix) + os.sep) for prefix in safe_prefixes):
            log.warning(
                "SECURITY: MEDIA_DIR '%s' is outside safe directories "
                "(home, /media/, /mnt/). This may be a misconfiguration.",
                resolved,
            )
    except Exception as exc:
        log.warning("SECURITY: Failed to validate MEDIA_DIR: %s", exc)

_validate_media_dir(MEDIA_DIR)


# --- Startup cleanup: remove leftover .tmp files from interrupted uploads ---


def _cleanup_tmp_files():
    """Remove .tmp files left behind by interrupted atomic uploads.

    These occur when power is lost or the process is killed mid-upload.
    They are incomplete files that should never be served or played.
    """
    media_path = Path(MEDIA_DIR)
    if not media_path.exists():
        return
    cleaned = 0
    for tmp_file in media_path.glob("*.tmp"):
        try:
            tmp_file.unlink()
            cleaned += 1
        except OSError as exc:
            log.warning("Failed to clean up temp file %s: %s", tmp_file, exc)
    if cleaned:
        log.info("Startup cleanup: removed %d leftover .tmp file(s) from interrupted uploads", cleaned)


_cleanup_tmp_files()


# --- Request timeout ---

UPLOAD_TIMEOUT_SECONDS = 300


def request_timeout(timeout_seconds):
    """Decorator to enforce a timeout on request handlers.

    Prevents hung connections from consuming the thread forever.
    Uses SIGALRM on Unix systems; on Windows this is a no-op.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(signal, "SIGALRM"):
                # Windows or system without SIGALRM - skip timeout
                return f(*args, **kwargs)

            def _timeout_handler(signum, frame):
                raise TimeoutError(f"Request timed out after {timeout_seconds} seconds")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            try:
                return f(*args, **kwargs)
            except TimeoutError:
                log.error("Upload request timed out after %ds from %s", timeout_seconds, request.remote_addr)
                abort(408)  # Request Timeout
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        return decorated
    return decorator


# --- Flask app ---

app = Flask(
    __name__,
    template_folder=str(SCRIPT_DIR / "templates"),
    static_folder=str(SCRIPT_DIR / "static"),
)

# Stable secret key: read from .env, generate and persist if missing
_secret = config.get("FLASK_SECRET_KEY", "")
if not _secret:
    _secret = secrets.token_hex(24)
    config.save({"FLASK_SECRET_KEY": _secret})
app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Register API blueprint
app.register_blueprint(api)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "media-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com"
    )
    return response


# --- PIN authentication ---


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
    """Decorator to require HTTP Basic Auth on POST routes when WEB_PASSWORD is set.

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


# --- Request logging ---


def log_post_request(f):
    """Decorator to log POST requests with client IP and route."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        log.info(
            "POST %s from %s",
            request.path,
            request.remote_addr,
        )
        return f(*args, **kwargs)
    return decorated


# --- Post-upload processing ---


def _generate_video_thumbnail(video_path, filename):
    """Generate a thumbnail for a video file using ffmpeg.

    Grabs a frame at 1 second and saves it as a JPEG in the thumbnails dir.
    Silently skips if ffmpeg is not installed.
    """
    try:
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        thumb_name = Path(filename).stem + ".jpg"
        thumb_path = Path(THUMBNAIL_DIR) / thumb_name
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", "1",
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=320:-1",
                "-q:v", "5",
                str(thumb_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            log.info("Thumbnail generated: %s", thumb_name)
        else:
            log.warning("Thumbnail generation produced empty file for %s", filename)
    except FileNotFoundError:
        log.debug("ffmpeg not found, skipping thumbnail for %s", filename)
    except Exception as exc:
        log.warning("Thumbnail generation failed for %s: %s", filename, exc)


def _auto_resize_image(image_path):
    """Downscale an image if it exceeds AUTO_RESIZE_MAX on its longest side.

    Uses Pillow. Silently skips if Pillow is not installed.
    """
    if AUTO_RESIZE_MAX <= 0:
        return
    try:
        from PIL import Image as PILImage
    except ImportError:
        log.debug("Pillow not installed, skipping auto-resize")
        return
    try:
        # Limit decompression to ~178MP (1GB RAM) to prevent OOM on Pi 3B.
        # Default Pillow limit is 178MP but we lower it for safety on 1GB devices.
        PILImage.MAX_IMAGE_PIXELS = 50_000_000  # ~50MP, ~200MB decompressed
        with PILImage.open(str(image_path)) as img:
            w, h = img.size
            max_dim = AUTO_RESIZE_MAX
            if w <= max_dim and h <= max_dim:
                return
            # Preserve aspect ratio: scale so longest side == max_dim
            ratio = min(max_dim / w, max_dim / h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            resized = img.resize((new_w, new_h), PILImage.LANCZOS)
            # Preserve EXIF orientation if present
            exif = img.info.get("exif")
            save_kwargs = {"quality": 90}
            if exif:
                save_kwargs["exif"] = exif
            resized.save(str(image_path), **save_kwargs)
            log.info("Resized %s: %dx%d -> %dx%d", image_path.name, w, h, new_w, new_h)
    except Exception as exc:
        log.warning("Auto-resize failed for %s: %s", image_path.name, exc)


# --- Routes ---


@app.route("/")
def index():
    files = media.get_media_files()
    disk = media.get_disk_usage()
    photo_count = sum(1 for f in files if not f["is_video"])
    video_count = sum(1 for f in files if f["is_video"])
    # Check if any photos have GPS locations for the Map nav link
    has_locations = bool(media.get_photo_locations())
    return render_template(
        "index.html",
        files=files,
        disk=disk,
        photo_count=photo_count,
        video_count=video_count,
        max_upload_mb=MAX_UPLOAD_MB,
        has_locations=has_locations,
    )


@app.route("/upload", methods=["POST"])
@require_pin
@log_post_request
@request_timeout(UPLOAD_TIMEOUT_SECONDS)
def upload():
    # Limit concurrent uploads to prevent OOM on Pi 3B (1GB RAM)
    if not _upload_semaphore.acquire(blocking=False):
        flash("Another upload is in progress. Please wait and try again.", "warning")
        return redirect(url_for("index"))
    try:
        return _do_upload()
    finally:
        _upload_semaphore.release()


def _do_upload():
    if "files" not in request.files:
        flash("No files selected", "error")
        return redirect(url_for("index"))

    # Check disk space before accepting uploads (reserve 50MB for system use)
    disk = media.get_disk_usage()
    if disk["percent"] >= 95 or disk.get("free_bytes", 0) < 50 * 1024 * 1024:
        flash("Not enough disk space. Delete files or use a larger SD card.", "error")
        return redirect(url_for("index"))

    uploaded = 0
    skipped = 0
    for f in request.files.getlist("files"):
        if f.filename == "":
            continue
        if not f or not media.allowed_file(f.filename):
            skipped += 1
            continue

        filename = secure_filename(f.filename)
        if not filename:
            skipped += 1
            continue

        # Re-check disk space before each file to prevent filling disk
        # during multi-file uploads
        current_disk = media.get_disk_usage()
        if current_disk["percent"] >= 95 or current_disk.get("free_bytes", 0) < 50 * 1024 * 1024:
            flash(f"Disk full after uploading {uploaded} file(s). Remaining files skipped.", "warning")
            break

        dest = Path(MEDIA_DIR) / filename
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            filename = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
            dest = Path(MEDIA_DIR) / filename

        # Atomic upload: write to .tmp file, fsync, then rename.
        # This prevents truncated/corrupt files if power is lost mid-upload.
        tmp_dest = Path(MEDIA_DIR) / (filename + ".tmp")
        try:
            f.save(str(tmp_dest))
            # fsync to ensure data is on disk before rename
            with open(str(tmp_dest), "rb") as fd:
                os.fsync(fd.fileno())
            # Atomic rename - on same filesystem this is atomic
            os.replace(str(tmp_dest), str(dest))
        except Exception:
            # Clean up temp file on any failure
            try:
                tmp_dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        log.info("Uploaded: %s (%s)", filename, media.format_size(dest.stat().st_size))

        # Post-upload processing
        if media.is_video(filename):
            _generate_video_thumbnail(dest, filename)
        else:
            _auto_resize_image(dest)
            # Extract GPS and update location cache
            coords = media.extract_gps(dest)
            media.update_location_cache(filename, coords)

        uploaded += 1

    if uploaded > 0:
        flash(f"Uploaded {uploaded} file(s) successfully", "success")
    if skipped > 0:
        flash(f"Skipped {skipped} file(s) (unsupported format)", "warning")

    return redirect(url_for("index"))


@app.route("/delete", methods=["POST"])
@require_pin
@log_post_request
def delete():
    filename = request.form.get("filename", "")
    if not filename:
        flash("No file specified", "error")
        return redirect(url_for("index"))

    filepath = Path(MEDIA_DIR) / filename
    # Prevent path traversal
    try:
        filepath.resolve().relative_to(Path(MEDIA_DIR).resolve())
    except ValueError:
        flash("Invalid file path", "error")
        return redirect(url_for("index"))

    if filepath.exists() and filepath.is_file():
        # Remove associated thumbnail if it exists
        thumb_path = Path(THUMBNAIL_DIR) / (filepath.stem + ".jpg")
        if thumb_path.exists():
            thumb_path.unlink()
        # Remove from GPS locations cache
        media.remove_from_location_cache(filepath.name)
        filepath.unlink()
        log.info("Deleted: %s", filename)
        flash("File deleted", "success")
    else:
        flash("File not found", "error")

    return redirect(url_for("index"))


@app.route("/delete-all", methods=["POST"])
@require_pin
@log_post_request
def delete_all():
    confirm = request.form.get("confirm", "")
    if confirm != "DELETE":
        flash("Type DELETE to confirm", "error")
        return redirect(url_for("index"))

    media_path = Path(MEDIA_DIR)
    image_ext, video_ext = media.get_allowed_extensions()
    all_ext = image_ext | video_ext
    count = 0
    for f in media_path.iterdir():
        if f.is_file() and f.suffix.lower() in all_ext:
            f.unlink()
            count += 1
    # Clean up all thumbnails
    thumb_dir = Path(THUMBNAIL_DIR)
    if thumb_dir.exists():
        for t in thumb_dir.iterdir():
            if t.is_file():
                t.unlink()
    # Clear GPS locations cache
    cache_path = Path(MEDIA_DIR) / ".locations.json"
    if cache_path.exists():
        try:
            cache_path.unlink()
        except OSError:
            pass
    log.info("Deleted all: %d files", count)
    flash(f"Deleted {count} file(s)", "success")
    return redirect(url_for("index"))


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(
        MEDIA_DIR, filename, mimetype=None
    )


@app.route("/thumbnail/<filename>")
def serve_thumbnail(filename):
    """Serve a video thumbnail image."""
    thumb_name = Path(filename).stem + ".jpg"
    thumb_path = Path(THUMBNAIL_DIR) / thumb_name
    if thumb_path.exists():
        return send_from_directory(THUMBNAIL_DIR, thumb_name)
    # No thumbnail available - return 404
    abort(404)


@app.route("/map")
def map_page():
    """Map page showing photo locations."""
    return render_template("map.html")


@app.route("/settings")
def settings_page():
    """Settings page to configure the display."""
    env = config.load_env()
    return render_template("settings.html", env=env)


@app.route("/settings", methods=["POST"])
@require_pin
@log_post_request
def settings_save():
    """Save settings from the settings form."""
    updates = {}
    # Security: MEDIA_DIR and WEB_PORT excluded from web editing.
    # MEDIA_DIR change enables arbitrary file read/write.
    # WEB_PORT change could lock users out.
    allowed_keys = {
        "PHOTO_DURATION",
        "SHUFFLE",
        "LOOP",
        "MAX_UPLOAD_MB",
        "AUTO_RESIZE_MAX",
        "HDMI_SCHEDULE_ENABLED",
        "HDMI_OFF_TIME",
        "HDMI_ON_TIME",
        "AUTO_REFRESH",
        "REFRESH_INTERVAL",
        "IMAGE_EXTENSIONS",
        "VIDEO_EXTENSIONS",
    }

    for key in allowed_keys:
        value = request.form.get(key)
        if value is not None:
            updates[key] = value.strip()

    # Validate numeric fields
    for key in ("PHOTO_DURATION", "REFRESH_INTERVAL", "MAX_UPLOAD_MB"):
        if key in updates:
            try:
                val = int(updates[key])
                if val < 1:
                    raise ValueError
            except ValueError:
                flash(f"Invalid value for {key}: must be a positive number", "error")
                return redirect(url_for("settings_page"))

    # Validate time fields
    for key in ("HDMI_OFF_TIME", "HDMI_ON_TIME"):
        if key in updates:
            parts = updates[key].split(":")
            if len(parts) != 2:
                flash(f"Invalid time format for {key}: use HH:MM", "error")
                return redirect(url_for("settings_page"))
            try:
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except ValueError:
                flash(f"Invalid time for {key}: use HH:MM (0-23:0-59)", "error")
                return redirect(url_for("settings_page"))

    # Validate file extensions against a forbidden list to prevent
    # dangerous file types from being accepted as media.
    forbidden_ext = {
        ".html", ".htm", ".js", ".svg", ".php",
        ".py", ".sh", ".exe", ".bat", ".cmd",
    }
    for ext_key in ("IMAGE_EXTENSIONS", "VIDEO_EXTENSIONS"):
        if ext_key in updates:
            exts = [
                e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
                for e in updates[ext_key].split(",")
                if e.strip()
            ]
            bad = [e for e in exts if e in forbidden_ext]
            if bad:
                flash(
                    f"Forbidden extension(s) in {ext_key}: {', '.join(bad)}",
                    "error",
                )
                return redirect(url_for("settings_page"))

    config.save(updates)
    log.info("Settings updated: %s", list(updates.keys()))

    # Auto-restart slideshow if checkbox was checked
    if request.form.get("auto_restart") == "1":
        success, _ = services.restart_slideshow()
        if success:
            flash("Settings saved and slideshow restarted.", "success")
        else:
            flash("Settings saved but failed to restart slideshow.", "warning")
    else:
        flash("Settings saved. Restart services for changes to take effect.", "success")

    return redirect(url_for("settings_page"))


# --- Periodic thumbnail cleanup ---
_thumbnail_cleanup_last = 0
_THUMBNAIL_CLEANUP_INTERVAL = 3600  # hourly


@app.before_request
def _periodic_thumbnail_cleanup():
    """Run orphan thumbnail cleanup hourly, triggered by any request."""
    global _thumbnail_cleanup_last
    now = time.monotonic()
    if now - _thumbnail_cleanup_last > _THUMBNAIL_CLEANUP_INTERVAL:
        _thumbnail_cleanup_last = now
        try:
            removed = media.cleanup_orphan_thumbnails()
            if removed:
                log.info("Cleaned up %d orphan thumbnail(s)", removed)
        except Exception:
            pass


@app.route("/api/restart-slideshow", methods=["POST"])
@require_pin
@log_post_request
def restart_slideshow():
    success, message = services.restart_slideshow()
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"status": "error", "message": message}), 500


@app.route("/api/reboot", methods=["POST"])
@require_pin
@log_post_request
def api_reboot():
    try:
        log.info("Reboot requested via web UI")
        subprocess.Popen(["sudo", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "ok", "message": "Device is rebooting..."})
    except Exception:
        log.error("Failed to reboot")
        return jsonify({"status": "error", "message": "Failed to reboot"}), 500


@app.route("/api/shutdown", methods=["POST"])
@require_pin
@log_post_request
def api_shutdown():
    try:
        log.info("Shutdown requested via web UI")
        subprocess.Popen(["sudo", "shutdown", "-h", "now"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "ok", "message": "Device is shutting down..."})
    except Exception:
        log.error("Failed to shut down")
        return jsonify({"status": "error", "message": "Failed to shut down"}), 500


if __name__ == "__main__":
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    log.info("Pi Photo Display - Web Upload Server")
    log.info("Media directory: %s", MEDIA_DIR)
    log.info("Listening on http://0.0.0.0:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
