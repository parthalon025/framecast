#!/usr/bin/env python3
"""Web upload server for FrameCast.

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
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename

import sse
from api import api
from modules import config, db, media, wifi
from modules.auth import auth_api, require_pin, validate_guest_token
from modules.boot_config import apply_boot_config, apply_boot_ssh

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# --- Runtime worker-count guard ---


def _check_single_worker():
    """Guard against multi-worker misconfiguration (Lesson #1356).

    SSE client list, stats buffer, and CEC state are process-local.
    Multiple workers silently break real-time updates and stats accuracy.
    """
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("GUNICORN_WORKERS")
    if workers and workers not in ("", "1"):
        raise RuntimeError(
            f"FrameCast requires exactly 1 gunicorn worker (got {workers}). "
            "SSE, stats buffer, and CEC state are process-singletons."
        )


# --- Self-healing .env ---


def _heal_env_file():
    """If .env is missing or empty, restore from .env.example and regenerate secrets.

    This prevents silent fallback to defaults which can cause subtle issues
    (wrong media directory, no secret key, etc.) after SD card corruption.
    """
    env_file = Path(__file__).parent / ".env"
    env_example = Path(__file__).parent / ".env.example"

    if env_file.exists() and env_file.stat().st_size > 10:
        _ensure_access_pin()
        return  # .env looks valid

    if not env_file.exists():
        log.critical(".env file missing at %s", env_file)
    else:
        log.critical(
            ".env file is empty or corrupt at %s (size: %d bytes)",
            env_file,
            env_file.stat().st_size,
        )

    if env_example.exists():
        log.warning("Self-healing: Restoring .env from .env.example")
        shutil.copy2(str(env_example), str(env_file))
        # Regenerate the secret key in the restored file
        new_secret = secrets.token_hex(24)
        config.save({"FLASK_SECRET_KEY": new_secret})
        config.reload()
        log.warning("Self-healing: .env restored with new secret key. Review settings.")
    else:
        log.critical(
            "No .env.example found - cannot self-heal. Using built-in defaults."
        )

    _ensure_access_pin()


def _ensure_access_pin():
    """Generate a random ACCESS_PIN if not already set.

    Respects PIN_LENGTH setting (4 or 6 digits, default 4).
    """
    from modules.auth import generate_pin

    existing = config.get("ACCESS_PIN", "").strip()
    if existing:
        return  # PIN already configured

    try:
        pin_length = int(config.get("PIN_LENGTH", "4"))
        if pin_length not in (4, 6):
            pin_length = 4
    except (TypeError, ValueError):
        pin_length = 4

    pin = generate_pin(pin_length)
    config.save({"ACCESS_PIN": pin})
    config.reload()
    log.info("Generated new %d-digit ACCESS_PIN (shown on TV display)", pin_length)


_heal_env_file()

# Rotate PIN on boot if configured
from modules.auth import rotate_pin_on_boot  # noqa: E402 — must run after _heal_env_file()

rotate_pin_on_boot()


# --- Config ---

SCRIPT_DIR = Path(__file__).parent
VERSION_FILE = SCRIPT_DIR.parent / "VERSION"


def _read_version():
    """Read version string from VERSION file for cache-busting."""
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "dev"


MEDIA_DIR = media.get_media_dir()
THUMBNAIL_DIR = str(Path(MEDIA_DIR) / "thumbnails")
PORT = int(config.get("WEB_PORT", "8080"))
MAX_UPLOAD_MB = int(config.get("MAX_UPLOAD_MB", "200"))
AUTO_RESIZE_MAX = int(config.get("AUTO_RESIZE_MAX", "1920"))

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
        if not any(
            resolved == prefix or str(resolved).startswith(str(prefix) + os.sep)
            for prefix in safe_prefixes
        ):
            log.warning(
                "SECURITY: MEDIA_DIR '%s' is outside safe directories "
                "(home, /media/, /mnt/). This may be a misconfiguration.",
                resolved,
            )
    except Exception as exc:
        log.warning("SECURITY: Failed to validate MEDIA_DIR: %s", exc)


_validate_media_dir(MEDIA_DIR)


def _validate_upload_path(filepath, media_dir):
    """Ensure resolved upload path stays within MEDIA_DIR (Lesson #37).

    Prevents path traversal if MEDIA_DIR is reconfigured at runtime.
    """
    resolved = Path(filepath).resolve()
    media_resolved = Path(media_dir).resolve()
    if (
        not str(resolved).startswith(str(media_resolved) + os.sep)
        and resolved != media_resolved
    ):
        log.error("Path traversal blocked: %s is outside %s", resolved, media_resolved)
        raise ValueError(f"Upload path outside media directory: {resolved}")


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
        log.info(
            "Startup cleanup: removed %d leftover .tmp file(s) from interrupted uploads",
            cleaned,
        )


_cleanup_tmp_files()

# --- Boot partition WiFi config ---
apply_boot_config()

# --- Boot partition SSH flag (Issue #4) ---
apply_boot_ssh()

# --- Recover stale AP after crash/restart (Issue #35) ---
wifi.check_stale_ap()

# --- Auto-start AP if no WiFi configured (first boot flow) ---
try:
    if not wifi.is_connected():
        log.info("No WiFi connection detected — starting AP for onboarding")
        wifi.start_ap()
except Exception as e:
    log.warning("AP auto-start failed: %s", e)

# --- WiFi connectivity watchdog (Issue #105) ---
wifi.start_wifi_watchdog()

# --- Initialize SQLite content model ---
db.init_db()
db.vacuum_if_needed()
db.register_shutdown_flush()


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

            # SIGALRM only works in the main thread; gthread workers
            # dispatch requests to non-main threads where signal.signal()
            # raises ValueError.  Fall back to gunicorn's own timeout.
            if threading.current_thread() is not threading.main_thread():
                return f(*args, **kwargs)

            def _timeout_handler(signum, frame):
                raise TimeoutError(f"Request timed out after {timeout_seconds} seconds")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            try:
                return f(*args, **kwargs)
            except TimeoutError:
                log.error(
                    "Upload request timed out after %ds from %s",
                    timeout_seconds,
                    request.remote_addr,
                )
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
_check_single_worker()

# Stable secret key: read from .env, generate and persist if missing
_secret = config.get("FLASK_SECRET_KEY", "")
if not _secret:
    _secret = secrets.token_hex(24)
    config.save({"FLASK_SECRET_KEY": _secret})
app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Register API blueprints
app.register_blueprint(api)
app.register_blueprint(auth_api)


# ---------------------------------------------------------------------------
# Captive portal detection — iOS/Android probe these URLs on new networks.
# When the Pi is in AP mode, NM shared mode routes all DNS back to us, so
# these probes land here. A 302 to /setup triggers the OS captive portal popup.
# ---------------------------------------------------------------------------

from flask import redirect  # noqa: E402 — imported here to co-locate with route


@app.route("/generate_204")
@app.route("/hotspot-detect.html")
@app.route("/connecttest.txt")
@app.route("/ncsi.txt")
def captive_portal_redirect():
    """Redirect captive portal probes to the setup page."""
    return redirect("/setup", code=302)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "media-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    return response


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
                "ffmpeg",
                "-y",
                "-ss",
                "1",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-vf",
                "scale=320:-1",
                "-q:v",
                "5",
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
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        log.warning("Thumbnail generation failed for %s: %s", filename, exc)


def _auto_resize_image(image_path):
    """Downscale an image if it exceeds AUTO_RESIZE_MAX on its longest side.

    Uses Pillow. Silently skips if Pillow is not installed.

    Note: No per-image SIGALRM here. SIGALRM is process-global and races
    across gthread workers. The outer request_timeout (300s) provides the
    safety net. See Python Expert review finding.
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
            # Atomic write: save to tmp, then rename (I21 — prevents corrupt on power loss)
            tmp_path = str(image_path) + ".tmp"
            try:
                resized.save(tmp_path, **save_kwargs)
                os.replace(tmp_path, str(image_path))
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            log.info("Resized %s: %dx%d -> %dx%d", image_path.name, w, h, new_w, new_h)
    except Exception as exc:
        log.warning("Auto-resize failed for %s: %s", image_path.name, exc)


# --- Routes ---


@app.route("/")
def index():
    return render_template("spa.html", version=_read_version())


def _require_pin_or_guest(func):
    """Like require_pin, but also accepts a valid guest_token query param.

    Guest tokens grant upload-only access — no other routes accept them.
    """

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        # Check guest token first (query param on upload URL)
        guest_token = request.args.get("guest_token", "")
        if guest_token and validate_guest_token(guest_token):
            log.info(
                "Guest upload authorized (token valid) from %s", request.remote_addr
            )
            return func(*args, **kwargs)
        # Fall through to normal PIN auth
        return require_pin(func)(*args, **kwargs)

    return decorated


@app.route("/upload", methods=["POST"])
@_require_pin_or_guest
@log_post_request
@request_timeout(UPLOAD_TIMEOUT_SECONDS)
def upload():
    # Limit concurrent uploads to prevent OOM on Pi 3B (1GB RAM)
    if not _upload_semaphore.acquire(blocking=False):
        return jsonify({"error": "Another upload is in progress"}), 429
    try:
        return _do_upload()
    finally:
        _upload_semaphore.release()


def _do_upload():
    if "files" not in request.files:
        return jsonify({"error": "No files selected"}), 400

    # Check disk space before accepting uploads (reserve 50MB for system use)
    disk = media.get_disk_usage()
    if disk["percent"] >= 95 or disk.get("free_bytes", 0) < 50 * 1024 * 1024:
        return jsonify({"error": "Not enough disk space"}), 507

    # Read uploader identity from cookie (set by "Who's uploading?" modal)
    uploaded_by = request.cookies.get("framecast_user", "default").strip() or "default"
    # Ensure user exists in DB (auto-create on first upload)
    db.get_or_create_user(uploaded_by)

    uploaded = 0
    uploaded_names = []
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
        if (
            current_disk["percent"] >= 95
            or current_disk.get("free_bytes", 0) < 50 * 1024 * 1024
        ):
            break

        dest = Path(MEDIA_DIR) / filename
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            filename = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
            dest = Path(MEDIA_DIR) / filename

        # Per-upload path traversal guard (Issue #37)
        try:
            _validate_upload_path(dest, MEDIA_DIR)
        except ValueError:
            skipped += 1
            continue

        is_vid = media.is_video(filename)

        # DB INSERT before file write (Lesson #1670) — quarantined until file is safe
        try:
            photo_id = db.insert_photo(
                filename=filename,
                filepath=str(dest),
                is_video=is_vid,
                uploaded_by=uploaded_by,
                quarantined=True,
                quarantine_reason="upload in progress",
            )
        except Exception as db_exc:
            if "UNIQUE" in str(db_exc):
                log.warning("Duplicate filename in DB: %s", filename)
                skipped += 1
                continue
            log.error("DB insert failed for %s: %s", filename, db_exc)
            skipped += 1
            continue

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
        except Exception as write_exc:
            # Clean up temp file on any failure
            log.error("File write failed for %s: %s", filename, write_exc)
            try:
                tmp_dest.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                log.warning(
                    "Failed to clean up temp file %s: %s", tmp_dest, cleanup_exc
                )
            # Mark DB record as quarantined with reason
            db.update_photo_quarantine(photo_id, True, "file write failed")
            skipped += 1
            continue
        log.info("Uploaded: %s (%s)", filename, media.format_size(dest.stat().st_size))

        # Validate image integrity before processing
        if not is_vid:
            try:
                from PIL import Image as PILImage

                with PILImage.open(str(dest)) as check_img:
                    check_img.verify()
            except Exception as verify_exc:
                log.warning("Corrupt image detected: %s — %s", filename, verify_exc)
                quarantine_dir = Path(MEDIA_DIR) / "quarantine"
                quarantine_dir.mkdir(exist_ok=True)
                quarantine_dest = quarantine_dir / filename
                try:
                    dest.rename(quarantine_dest)
                    log.info("Quarantined corrupt file: %s", filename)
                except OSError as mv_exc:
                    log.error("Failed to quarantine %s: %s", filename, mv_exc)
                db.update_photo_quarantine(photo_id, True, "corrupt image")
                skipped += 1
                continue

        # Post-upload processing — wrapped to quarantine on unexpected crashes
        # (verify() only checks headers; corrupt data can still crash processing)
        try:
            gps_lat, gps_lon = None, None
            file_size = dest.stat().st_size
            width, height = None, None
            checksum = None

            if is_vid:
                _generate_video_thumbnail(dest, filename)
            else:
                media.fix_orientation(dest)
                _auto_resize_image(dest)
                # Extract GPS
                coords = media.extract_gps(dest)
                if coords:
                    gps_lat, gps_lon = coords
                # Strip EXIF metadata for privacy (GPS already extracted above) (I27)
                media.strip_exif(dest)
                # Get dimensions
                try:
                    from PIL import Image as PILImage

                    with PILImage.open(str(dest)) as img:
                        width, height = img.size
                except Exception as exc:
                    log.warning("Failed to extract dimensions for %s: %s", filename, exc)

            # Compute checksum
            try:
                checksum = db.compute_sha256(str(dest))
            except Exception as exc:
                log.warning("Failed to compute checksum for %s: %s", filename, exc)

            # Compute perceptual hash for duplicate detection
            dhash = None
            if not is_vid:
                dhash = media.compute_dhash(str(dest))
                if dhash:
                    near_dupes = db.find_near_duplicates(dhash)
                    if near_dupes:
                        dupe_names = [d["filename"] for d in near_dupes[:3]]
                        log.info("Near-duplicate detected for %s: %s", filename, dupe_names)

            # Unquarantine and update metadata in DB
            db.unquarantine_photo(
                photo_id, file_size, width, height, checksum, gps_lat, gps_lon, dhash=dhash
            )
        except Exception as proc_exc:
            log.error(
                "Post-upload processing failed for %s, quarantining: %s",
                filename, proc_exc,
            )
            db.update_photo_quarantine(photo_id, True, "processing failed")
            skipped += 1
            continue

        uploaded += 1
        uploaded_names.append(filename)
        sse.notify("photo:added", {"filename": filename, "photo_id": photo_id})

    return jsonify(
        {
            "uploaded": uploaded_names,
            "uploaded_count": uploaded,
            "skipped": skipped,
        }
    ), 200 if uploaded > 0 else 400


@app.route("/delete", methods=["POST"])
@require_pin
@log_post_request
def delete():
    filename = request.form.get("filename", "")
    if not filename:
        return jsonify({"error": "No file specified"}), 400

    filepath = Path(MEDIA_DIR) / filename
    # Prevent path traversal
    try:
        filepath.resolve().relative_to(Path(MEDIA_DIR).resolve())
    except ValueError:
        return jsonify({"error": "Invalid file path"}), 400

    if filepath.exists() and filepath.is_file():
        # Mark as quarantined in DB first, then delete file async
        photo_row = db.get_photo_by_filename(filename)
        if photo_row:
            db.update_photo_quarantine(photo_row["id"], True, "deleted by user")

        # Remove associated thumbnail if it exists
        thumb_path = Path(THUMBNAIL_DIR) / (filepath.stem + ".jpg")
        try:
            if thumb_path.exists():
                thumb_path.unlink()
        except OSError as exc:
            log.warning("Failed to remove thumbnail for %s: %s", filepath.name, exc)

        try:
            filepath.unlink()
        except OSError as exc:
            log.error(
                "Failed to delete file %s: %s — un-quarantining in DB",
                filepath.name,
                exc,
            )
            if photo_row:
                db.update_photo_quarantine(photo_row["id"], False, None)
            return jsonify({"error": "File deletion failed"}), 500
        log.info("Deleted: %s", filename)
        sse.notify("photo:deleted", {"filename": filename})
        return jsonify({"status": "ok", "filename": filename})

    return jsonify({"error": "File not found"}), 404


@app.route("/delete-all", methods=["POST"])
@require_pin
@log_post_request
def delete_all():
    data = request.get_json(silent=True) or {}
    confirm = data.get("confirm", request.form.get("confirm", ""))
    if confirm != "DELETE":
        return jsonify({"error": "Type DELETE to confirm"}), 400

    media_path = Path(MEDIA_DIR)
    image_ext, video_ext = media.get_allowed_extensions()
    all_ext = image_ext | video_ext

    # Phase 1: Delete files first (C15 — frees disk space even if DB fails on full disk)
    count = 0
    deleted_filenames = []
    for f in media_path.iterdir():
        if f.is_file() and f.suffix.lower() in all_ext:
            try:
                f.unlink()
                count += 1
                deleted_filenames.append(f.name)
            except OSError as exc:
                log.warning("Failed to delete %s during delete-all: %s", f.name, exc)

    # Phase 2: Clean up DB records for successfully deleted files only
    if deleted_filenames:
        try:
            db.bulk_quarantine_by_filenames(deleted_filenames, reason="bulk delete")
            log.info(
                "Bulk-quarantined %d photos in DB after delete-all",
                len(deleted_filenames),
            )
        except Exception as db_exc:
            log.error("Failed to clean up DB records after delete-all: %s", db_exc)
    # Clean up all thumbnails
    thumb_dir = Path(THUMBNAIL_DIR)
    if thumb_dir.exists():
        for t in thumb_dir.iterdir():
            if t.is_file():
                try:
                    t.unlink()
                except OSError as exc:
                    log.warning(
                        "Failed to delete thumbnail %s during delete-all: %s",
                        t.name,
                        exc,
                    )
    # Clear GPS locations cache
    cache_path = Path(MEDIA_DIR) / ".locations.json"
    if cache_path.exists():
        try:
            cache_path.unlink()
        except OSError as exc:
            log.warning("Failed to delete locations cache: %s", exc)
    log.info("Deleted all: %d files", count)
    return jsonify({"status": "ok", "deleted": count})


@app.route("/media/<path:filename>")
def serve_media(filename):
    if filename.startswith(("quarantine/", "quarantine\\")):
        abort(404)
    return send_from_directory(MEDIA_DIR, filename, mimetype=None)


@app.route("/thumbnail/<filename>")
def serve_thumbnail(filename):
    """Serve a video thumbnail image."""
    safe = secure_filename(filename)
    if not safe:
        abort(404)
    thumb_name = Path(safe).stem + ".jpg"
    thumb_path = Path(THUMBNAIL_DIR) / thumb_name
    if thumb_path.exists():
        return send_from_directory(THUMBNAIL_DIR, thumb_name)
    # No thumbnail available - return 404
    abort(404)


# --- Periodic thumbnail cleanup ---
_thumbnail_cleanup_last = 0
_THUMBNAIL_CLEANUP_INTERVAL = 3600  # hourly
_thumbnail_cleanup_lock = threading.Lock()


@app.before_request
def _periodic_thumbnail_cleanup():
    """Run orphan thumbnail cleanup hourly, triggered by any request."""
    global _thumbnail_cleanup_last
    if not _thumbnail_cleanup_lock.acquire(blocking=False):
        return  # Another thread is already cleaning
    try:
        now = time.monotonic()
        if now - _thumbnail_cleanup_last > _THUMBNAIL_CLEANUP_INTERVAL:
            _thumbnail_cleanup_last = now
            try:
                removed = media.cleanup_orphan_thumbnails()
                if removed:
                    log.info("Cleaned up %d orphan thumbnail(s)", removed)
            except Exception:
                log.warning("Periodic thumbnail cleanup failed", exc_info=True)
    finally:
        _thumbnail_cleanup_lock.release()


# --- SPA routes ---
# Serve the SPA shell for all client-side routes.


@app.route("/display")
@app.route("/display/<path:subpath>")
def display(subpath=None):
    return render_template("spa.html", version=_read_version())


@app.route("/setup")
def setup():
    return render_template("spa.html", version=_read_version())


@app.route("/update")
def update():
    return render_template("spa.html", version=_read_version())


@app.route("/map")
@app.route("/settings")
@app.route("/albums")
@app.route("/stats")
@app.route("/users")
def spa_phone_routes():
    """Serve SPA shell for all phone client-side routes."""
    return render_template("spa.html", version=_read_version())


if __name__ == "__main__":
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    log.info("FrameCast - Web Upload Server")
    log.info("Media directory: %s", MEDIA_DIR)
    log.info("Listening on http://0.0.0.0:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
