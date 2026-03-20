"""SQLite content model for FrameCast.

Manages photos, albums, tags, users, and display statistics.
All connections use WAL mode + busy_timeout for reliability on Pi hardware.
Write operations are serialized via _write_lock.
"""

import atexit
import hashlib
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from . import config, media

log = logging.getLogger(__name__)

# --- Write lock for all DB mutations (Lesson #1335) ---
_write_lock = threading.Lock()

# --- Stats buffering ---
_stats_buffer = []
_stats_buffer_lock = threading.Lock()
_STATS_FLUSH_THRESHOLD = 30
_STATS_FLUSH_INTERVAL = 300  # 5 minutes
_MAX_STATS_BUFFER = 500  # Cap to prevent OOM on persistent DB errors
_stats_last_flush = time.monotonic()
_flush_timer = None

# --- Schema version ---
CURRENT_SCHEMA_VERSION = 1

# --- SQL schema ---

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    filepath TEXT NOT NULL,
    mime_type TEXT,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    is_video BOOLEAN DEFAULT 0,
    checksum_sha256 TEXT,
    thumbnail_path TEXT,
    gps_lat REAL,
    gps_lon REAL,
    exif_date TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    uploaded_by TEXT DEFAULT 'default',
    is_favorite BOOLEAN DEFAULT 0,
    is_hidden BOOLEAN DEFAULT 0,
    view_count INTEGER DEFAULT 0,
    last_shown_at TEXT,
    quarantined BOOLEAN DEFAULT 0,
    quarantine_reason TEXT
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS album_photos (
    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    PRIMARY KEY (album_id, photo_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, tag_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    is_admin BOOLEAN DEFAULT 0,
    upload_count INTEGER DEFAULT 0,
    last_upload_at TEXT
);

CREATE TABLE IF NOT EXISTS display_stats (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    shown_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    duration_seconds REAL,
    transition_type TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
"""

_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_photos_favorite ON photos(is_favorite) WHERE is_favorite = 1;
CREATE INDEX IF NOT EXISTS idx_photos_hidden ON photos(is_hidden) WHERE is_hidden = 0;
CREATE INDEX IF NOT EXISTS idx_photos_uploaded_by ON photos(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_photos_last_shown ON photos(last_shown_at);
CREATE INDEX IF NOT EXISTS idx_display_stats_photo ON display_stats(photo_id);
CREATE INDEX IF NOT EXISTS idx_display_stats_shown ON display_stats(shown_at);
CREATE INDEX IF NOT EXISTS idx_photos_checksum ON photos(checksum_sha256);
"""

# --- Smart albums (computed queries) ---

SMART_ALBUMS = {
    "recent": {
        "name": "RECENT",
        "query": "uploaded_at > datetime('now', '-30 days')",
        "smart": True,
    },
    "on_this_day": {
        "name": "ON THIS DAY",
        "query": "strftime('%m-%d', exif_date) = strftime('%m-%d', 'now')",
        "smart": True,
    },
    "most_shown": {
        "name": "MOST SHOWN",
        "query": "1=1 ORDER BY view_count DESC LIMIT 20",
        "smart": True,
    },
}


def _db_path():
    """Return the Path to the FrameCast database file."""
    return Path(media.get_media_dir()) / "framecast.db"


def get_db():
    """Return a new SQLite connection with WAL mode and busy_timeout.

    Caller MUST wrap with ``contextlib.closing()``::

        with closing(get_db()) as conn:
            conn.execute(...)
    """
    conn = sqlite3.connect(str(_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables, indices, and run migrations if needed.

    Safe to call multiple times (idempotent).
    """
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _write_lock:
        with closing(get_db()) as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.executescript(_INDEX_SQL)

            # Check schema version
            row = conn.execute(
                "SELECT MAX(version) AS v FROM schema_version"
            ).fetchone()
            current = row["v"] if row and row["v"] is not None else 0

            if current < CURRENT_SCHEMA_VERSION:
                # Run migration from files if DB is empty
                migrate_from_files(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (CURRENT_SCHEMA_VERSION,),
                )
                conn.commit()
                # WAL checkpoint after migration
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            else:
                conn.commit()

    # Auto-prune old display stats on startup
    _prune_old_stats()

    # Auto-prune quarantined photos older than 30 days
    prune_quarantined()

    # Register atexit handler for stats buffer flush
    atexit.register(_flush_stats)

    # Start periodic flush timer
    _start_flush_timer()

    log.info("DATABASE: INITIALIZED at %s", db_path)


# --- Photo CRUD ---


def insert_photo(
    filename,
    filepath,
    mime_type=None,
    file_size=None,
    width=None,
    height=None,
    is_video=False,
    checksum_sha256=None,
    thumbnail_path=None,
    gps_lat=None,
    gps_lon=None,
    exif_date=None,
    uploaded_by="default",
    quarantined=False,
    quarantine_reason=None,
):
    """INSERT a new photo record. Returns the new row id."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                """INSERT INTO photos
                   (filename, filepath, mime_type, file_size, width, height,
                    is_video, checksum_sha256, thumbnail_path,
                    gps_lat, gps_lon, exif_date, uploaded_by,
                    quarantined, quarantine_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filename,
                    filepath,
                    mime_type,
                    file_size,
                    width,
                    height,
                    1 if is_video else 0,
                    checksum_sha256,
                    thumbnail_path,
                    gps_lat,
                    gps_lon,
                    exif_date,
                    uploaded_by,
                    1 if quarantined else 0,
                    quarantine_reason,
                ),
            )
            # Update user upload count in same transaction
            conn.execute(
                """UPDATE users SET upload_count = upload_count + 1,
                   last_upload_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE name = ?""",
                (uploaded_by,),
            )
            conn.commit()
            return cur.lastrowid


def get_photo_by_checksum(checksum):
    """Return a photo row matching the SHA256, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE checksum_sha256 = ?", (checksum,)
        ).fetchone()
        return dict(row) if row else None


def get_photo_by_id(photo_id):
    """Return a photo row by id, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
        return dict(row) if row else None


def get_photo_by_filename(filename):
    """Return a photo row by filename, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None


def get_photos(
    favorite_only=False,
    include_hidden=False,
    user=None,
    album_id=None,
    quarantined=False,
):
    """SELECT photos with optional filters.

    Returns a list of dicts.
    """
    conditions = []
    params = []

    if not quarantined:
        conditions.append("p.quarantined = 0")
    else:
        conditions.append("p.quarantined = 1")

    if favorite_only:
        conditions.append("p.is_favorite = 1")

    if not include_hidden:
        conditions.append("p.is_hidden = 0")

    if user:
        conditions.append("p.uploaded_by = ?")
        params.append(user)

    if album_id is not None:
        conditions.append(
            "p.id IN (SELECT photo_id FROM album_photos WHERE album_id = ?)"
        )
        params.append(album_id)

    where = " AND ".join(conditions) if conditions else "1=1"

    with closing(get_db()) as conn:
        rows = conn.execute(
            f"SELECT p.* FROM photos p WHERE {where} ORDER BY p.uploaded_at DESC LIMIT 500",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_playlist_candidates():
    """Get all non-quarantined, non-hidden photos for slideshow rotation."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT id, filename, uploaded_at, exif_date, is_favorite, view_count
               FROM photos WHERE quarantined = 0 AND is_hidden = 0"""
        ).fetchall()
        return [dict(r) for r in rows]


def update_photo_quarantine(photo_id, quarantined, reason=None):
    """Set quarantine status for a photo."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET quarantined = ?, quarantine_reason = ? WHERE id = ?",
                (1 if quarantined else 0, reason, photo_id),
            )
            conn.commit()


def toggle_favorite(photo_id):
    """Toggle is_favorite using atomic SQL toggle.

    Returns the new is_favorite value.
    """
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET is_favorite = NOT is_favorite WHERE id = ?",
                (photo_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT is_favorite FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            return bool(row["is_favorite"]) if row else None


def toggle_hidden(photo_id):
    """Toggle is_hidden using atomic SQL toggle."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET is_hidden = NOT is_hidden WHERE id = ?",
                (photo_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT is_hidden FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            return bool(row["is_hidden"]) if row else None


def unquarantine_photo(photo_id, file_size, width, height, checksum, gps_lat, gps_lon):
    """Clear quarantine and update metadata after successful upload processing."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                """UPDATE photos SET quarantined = 0, quarantine_reason = NULL,
                   file_size = ?, width = ?, height = ?,
                   checksum_sha256 = ?, gps_lat = ?, gps_lon = ?
                   WHERE id = ?""",
                (file_size, width, height, checksum, gps_lat, gps_lon, photo_id),
            )
            conn.commit()


def bulk_quarantine_all(reason="bulk delete"):
    """Mark all non-quarantined photos as quarantined."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET quarantined = 1, quarantine_reason = ? "
                "WHERE quarantined = 0",
                (reason,),
            )
            conn.commit()


def delete_photo(photo_id):
    """Mark a photo as quarantined (soft delete)."""
    update_photo_quarantine(photo_id, True, reason="deleted by user")


# --- Album CRUD ---


def create_album(name, description=None):
    """Create a new album. Returns the album id."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "INSERT INTO albums (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
            return cur.lastrowid


def get_albums():
    """Return all albums as a list of dicts, including photo_count."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT a.*,
                      (SELECT COUNT(*) FROM album_photos ap WHERE ap.album_id = a.id) AS photo_count
               FROM albums a
               ORDER BY a.sort_order, a.name"""
        ).fetchall()
        return [dict(r) for r in rows]


def delete_album(album_id):
    """Delete an album by id."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
            conn.commit()


def add_to_album(photo_id, album_id):
    """Add a photo to an album. Ignores duplicates."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?, ?)",
                (album_id, photo_id),
            )
            conn.commit()


def remove_from_album(photo_id, album_id):
    """Remove a photo from an album."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM album_photos WHERE album_id = ? AND photo_id = ?",
                (album_id, photo_id),
            )
            conn.commit()


def get_album_photos(album_id):
    """Return all photos in an album."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT p.* FROM photos p
               JOIN album_photos ap ON p.id = ap.photo_id
               WHERE ap.album_id = ?
               ORDER BY ap.added_at DESC
               LIMIT 500""",
            (album_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Tag CRUD ---


def add_tag(photo_id, tag_name):
    """Add a tag to a photo. Creates the tag if it doesn't exist.

    Returns the tag id.
    """
    with _write_lock:
        with closing(get_db()) as conn:
            # Get or create tag
            row = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()
            if row:
                tag_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO tags (name) VALUES (?)", (tag_name,)
                )
                tag_id = cur.lastrowid

            conn.execute(
                "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?)",
                (photo_id, tag_id),
            )
            conn.commit()
            return tag_id


def remove_tag(photo_id, tag_id):
    """Remove a tag from a photo."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM photo_tags WHERE photo_id = ? AND tag_id = ?",
                (photo_id, tag_id),
            )
            conn.commit()


def get_tags(photo_id):
    """Return all tags for a photo as a list of dicts."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT t.id, t.name FROM tags t
               JOIN photo_tags pt ON t.id = pt.tag_id
               WHERE pt.photo_id = ?
               ORDER BY t.name""",
            (photo_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_tags():
    """Return all tags in the system (for autocomplete)."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, name FROM tags ORDER BY name LIMIT 500"
        ).fetchall()
        return [dict(r) for r in rows]


# --- User CRUD ---


def create_user(name, is_admin=False):
    """Create a new user. Returns the user id."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "INSERT INTO users (name, is_admin) VALUES (?, ?)",
                (name, 1 if is_admin else 0),
            )
            conn.commit()
            return cur.lastrowid


def get_users():
    """Return all users as a list of dicts."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def get_or_create_user(name, is_admin=False):
    """Get a user by name, creating if needed. Returns the user id."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, is_admin) VALUES (?, ?)",
                (name, 1 if is_admin else 0),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM users WHERE name = ?", (name,)
            ).fetchone()
            return row["id"] if row else None


def create_user_returning_row(name):
    """Create a new user and return the full row as a dict.

    Raises sqlite3.IntegrityError if name already exists.
    """
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT INTO users (name) VALUES (?)", (name,)
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM users WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None


def delete_user_reassign(user_id):
    """Delete a user by id and reassign their photos to 'default'."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET uploaded_by = 'default' "
                "WHERE uploaded_by = (SELECT name FROM users WHERE id = ?)",
                (user_id,),
            )
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()


# --- Display stats buffering ---


def record_view(photo_id, duration=None, transition=None):
    """Buffer a display stat entry. Flushes on threshold or timer."""
    global _stats_last_flush
    entry = (photo_id, duration, transition)
    with _stats_buffer_lock:
        _stats_buffer.append(entry)
        count = len(_stats_buffer)

    if count >= _STATS_FLUSH_THRESHOLD:
        _flush_stats()


def _flush_stats():
    """Bulk INSERT buffered stats into the database."""
    global _stats_last_flush, _stats_buffer
    with _stats_buffer_lock:
        if not _stats_buffer:
            return
        batch = list(_stats_buffer)
        _stats_buffer.clear()

    try:
        with _write_lock:
            with closing(get_db()) as conn:
                conn.executemany(
                    """INSERT INTO display_stats (photo_id, duration_seconds, transition_type)
                       VALUES (?, ?, ?)""",
                    batch,
                )
                # Update view_count and last_shown_at on photos
                for photo_id, _dur, _trans in batch:
                    conn.execute(
                        """UPDATE photos SET view_count = view_count + 1,
                           last_shown_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                           WHERE id = ?""",
                        (photo_id,),
                    )
                conn.commit()
    except Exception:
        log.error("STATS: flush failed, re-queuing %d entries", len(batch), exc_info=True)
        with _stats_buffer_lock:
            if len(_stats_buffer) < _MAX_STATS_BUFFER:
                _stats_buffer.extend(batch)
            else:
                log.error("STATS: buffer full (%d), dropping %d entries to prevent OOM",
                           len(_stats_buffer), len(batch))
        return

    _stats_last_flush = time.monotonic()
    log.info("STATS: FLUSHED %d display entries", len(batch))


def _periodic_flush():
    """Called by timer thread to flush stats periodically."""
    try:
        _flush_stats()
    except Exception as exc:
        log.error("STATS: periodic flush error: %s", exc)
    finally:
        _start_flush_timer()


_flush_timer_lock = threading.Lock()


def _start_flush_timer():
    """Start the periodic stats flush timer."""
    global _flush_timer
    with _flush_timer_lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
        _flush_timer = threading.Timer(_STATS_FLUSH_INTERVAL, _periodic_flush)
        _flush_timer.daemon = True
        _flush_timer.start()


def _prune_old_stats():
    """DELETE display_stats older than 30 days."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "DELETE FROM display_stats WHERE shown_at < datetime('now', '-30 days')"
            )
            conn.commit()
            if cur.rowcount > 0:
                log.info("STATS: PRUNED %d entries older than 30 days", cur.rowcount)


def prune_quarantined(days=30):
    """Remove quarantined photos older than N days."""
    with _write_lock:
        with closing(get_db()) as conn:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor = conn.execute(
                "DELETE FROM photos WHERE quarantined = 1 AND uploaded_at < ?",
                (cutoff,),
            )
            conn.commit()
            count = cursor.rowcount
            if count:
                log.info("DB: pruned %d quarantined photos older than %d days", count, days)
            return count


# --- Aggregated stats ---


def get_stats():
    """Return aggregated display and content stats."""
    with closing(get_db()) as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE quarantined = 0"
        ).fetchone()["c"]
        favorites = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE is_favorite = 1 AND quarantined = 0"
        ).fetchone()["c"]
        hidden = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE is_hidden = 1 AND quarantined = 0"
        ).fetchone()["c"]
        videos = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE is_video = 1 AND quarantined = 0"
        ).fetchone()["c"]

        # By user
        by_user = conn.execute(
            """SELECT uploaded_by, COUNT(*) AS count FROM photos
               WHERE quarantined = 0
               GROUP BY uploaded_by ORDER BY count DESC"""
        ).fetchall()

        # Most shown (top 5)
        most_shown = conn.execute(
            """SELECT id, filename, view_count FROM photos
               WHERE quarantined = 0
               ORDER BY view_count DESC LIMIT 5"""
        ).fetchall()

        # Least shown (bottom 5 that have been shown at least once)
        least_shown = conn.execute(
            """SELECT id, filename, view_count FROM photos
               WHERE quarantined = 0 AND view_count > 0
               ORDER BY view_count ASC LIMIT 5"""
        ).fetchall()

        total_views = conn.execute(
            "SELECT COUNT(*) AS c FROM display_stats"
        ).fetchone()["c"]

    return {
        "total_photos": total,
        "favorites": favorites,
        "hidden": hidden,
        "videos": videos,
        "total_views": total_views,
        "by_user": [dict(r) for r in by_user],
        "most_shown": [dict(r) for r in most_shown],
        "least_shown": [dict(r) for r in least_shown],
    }


# --- Smart album queries ---


def get_smart_album_photos(smart_key):
    """Run a smart album query and return matching photos."""
    album_def = SMART_ALBUMS.get(smart_key)
    if not album_def:
        return []

    query_fragment = album_def["query"]
    # Smart album queries are pre-defined constants, not user input
    sql = f"SELECT * FROM photos WHERE quarantined = 0 AND {query_fragment}"

    with closing(get_db()) as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


# --- Backup ---


def backup_db():
    """Copy the database to framecast.db.backup using atomic write pattern.

    Returns the backup file path.
    """
    src = _db_path()
    if not src.exists():
        raise FileNotFoundError(f"Database not found: {src}")

    backup_path = src.parent / "framecast.db.backup"

    # WAL checkpoint before backup to ensure all data is in main DB file
    with closing(get_db()) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Atomic: copy to tmp, fsync, rename (Lesson #1234)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(src.parent), suffix=".db.tmp"
    )
    try:
        os.close(fd)
        shutil.copy2(str(src), tmp_path)
        # fsync the copy
        with open(tmp_path, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp_path, str(backup_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    log.info("BACKUP: COMPLETE → %s", backup_path)
    return str(backup_path)


# --- WAL checkpoint (periodic) ---


def wal_checkpoint():
    """Run WAL checkpoint to reclaim space."""
    with closing(get_db()) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    log.info("DATABASE: WAL CHECKPOINT COMPLETE")


# --- Migration from files ---


def _compute_sha256(filepath):
    """Compute SHA256 hash of a file."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


# Public alias for external callers (web_upload.py etc.)
compute_sha256 = _compute_sha256


_pillow_warned = False


def _extract_exif_date(filepath):
    """Extract the EXIF date from an image file, or None."""
    global _pillow_warned
    try:
        from PIL import Image as PILImage
        from PIL import ExifTags
    except ImportError:
        if not _pillow_warned:
            log.warning("Pillow not installed — EXIF/dimension extraction disabled")
            _pillow_warned = True
        return None

    try:
        with PILImage.open(str(filepath)) as img:
            exif = img.getexif()
            if exif:
                # DateTimeOriginal (tag 36867) or DateTime (tag 306)
                date_str = exif.get(36867) or exif.get(306)
                return date_str
    except Exception as exc:
        log.warning("MIGRATION: EXIF extraction failed for %s: %s", filepath, exc)
    return None


def _get_image_dimensions(filepath):
    """Get (width, height) of an image, or (None, None)."""
    global _pillow_warned
    try:
        from PIL import Image as PILImage
    except ImportError:
        if not _pillow_warned:
            log.warning("Pillow not installed — EXIF/dimension extraction disabled")
            _pillow_warned = True
        return None, None

    try:
        with PILImage.open(str(filepath)) as img:
            return img.size
    except Exception as exc:
        log.warning("MIGRATION: image dimension extraction failed for %s: %s", filepath, exc)
        return None, None


def migrate_from_files(conn=None):
    """Scan MEDIA_DIR for media files and import them into the database.

    Reads existing GPS JSON cache and merges coordinates into photo rows.
    Creates a 'default' user. Idempotent: skips files already in DB.

    Args:
        conn: An existing DB connection (used during init_db). If None,
              opens a new connection.
    """
    media_dir = Path(media.get_media_dir())
    if not media_dir.exists():
        log.info("MIGRATION: MEDIA_DIR does not exist, skipping")
        return

    own_conn = conn is None
    if own_conn:
        conn = get_db()

    try:
        # Ensure default user exists
        existing = conn.execute(
            "SELECT id FROM users WHERE name = 'default'"
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (name, is_admin) VALUES ('default', 1)"
            )

        # Load existing GPS cache
        gps_cache = {}
        cache_path = media_dir / ".locations.json"
        if cache_path.exists():
            try:
                import json
                with open(cache_path, "r", encoding="utf-8") as f:
                    gps_cache = json.load(f)
            except Exception as exc:
                log.warning("MIGRATION: Failed to load GPS cache: %s", exc)

        # Gather media files
        image_ext, video_ext = media.get_allowed_extensions()
        all_ext = image_ext | video_ext
        skip_dirs = {media_dir / "thumbnails", media_dir / "quarantine"}

        media_files = []
        for f in media_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in all_ext:
                continue
            if any(skip_dir in f.parents for skip_dir in skip_dirs):
                continue
            if f.name.endswith(".tmp"):
                continue
            media_files.append(f)

        total = len(media_files)
        if total == 0:
            log.info("MIGRATION: No media files found")
            conn.commit()
            return

        log.info("MIGRATION: Found %d media files to index", total)

        imported = 0
        for idx, filepath in enumerate(media_files, 1):
            filename = filepath.name
            # Check if already in DB
            existing = conn.execute(
                "SELECT id FROM photos WHERE filename = ?", (filename,)
            ).fetchone()
            if existing:
                continue

            # Compute checksum
            checksum = _compute_sha256(filepath)

            # Check for duplicate checksum
            dup = conn.execute(
                "SELECT id FROM photos WHERE checksum_sha256 = ?", (checksum,)
            ).fetchone()
            if dup:
                log.info("MIGRATION: Skipping duplicate %s (matches id=%d)", filename, dup["id"])
                continue

            is_vid = filepath.suffix.lower() in video_ext
            file_size = filepath.stat().st_size

            # Extract metadata for images
            width, height = (None, None)
            exif_date = None
            gps_lat, gps_lon = None, None

            if not is_vid:
                width, height = _get_image_dimensions(filepath)
                exif_date = _extract_exif_date(filepath)

                # GPS from cache or extraction
                gps_entry = gps_cache.get(filename, {})
                if gps_entry.get("lat") is not None:
                    gps_lat = gps_entry["lat"]
                    gps_lon = gps_entry["lon"]
                else:
                    coords = media.extract_gps(filepath)
                    if coords:
                        gps_lat, gps_lon = coords

            # Determine thumbnail path for videos
            thumb_path = None
            if is_vid:
                thumb_file = media_dir / "thumbnails" / (filepath.stem + ".jpg")
                if thumb_file.exists():
                    thumb_path = str(thumb_file)

            # Determine MIME type
            mime_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".tiff": "image/tiff",
                ".mp4": "video/mp4",
                ".mkv": "video/x-matroska",
                ".avi": "video/x-msvideo",
                ".mov": "video/quicktime",
                ".webm": "video/webm",
                ".m4v": "video/x-m4v",
            }
            mime_type = mime_map.get(filepath.suffix.lower())

            conn.execute(
                """INSERT INTO photos
                   (filename, filepath, mime_type, file_size, width, height,
                    is_video, checksum_sha256, thumbnail_path,
                    gps_lat, gps_lon, exif_date, uploaded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'default')""",
                (
                    filename,
                    str(filepath),
                    mime_type,
                    file_size,
                    width,
                    height,
                    1 if is_vid else 0,
                    checksum,
                    thumb_path,
                    gps_lat,
                    gps_lon,
                    exif_date,
                ),
            )
            imported += 1

            if idx % 50 == 0 or idx == total:
                log.info("MIGRATION: %d/%d photos indexed", idx, total)

        conn.commit()

        # Delete old GPS JSON cache after successful migration
        if cache_path.exists() and imported > 0:
            try:
                cache_path.unlink()
                log.info("MIGRATION: Deleted old GPS cache (.locations.json)")
            except OSError as exc:
                log.warning("MIGRATION: Failed to delete GPS cache: %s", exc)

        log.info("MIGRATION: COMPLETE — %d new photos indexed", imported)

    finally:
        if own_conn:
            conn.close()
