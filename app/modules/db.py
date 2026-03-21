"""SQLite content model for FrameCast.

Manages photos, albums, tags, users, and display statistics.
All connections use WAL mode + busy_timeout for reliability on Pi hardware.
Write operations are serialized via _write_lock.
"""
from __future__ import annotations

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
from typing import Any

from . import media

log = logging.getLogger(__name__)

# --- Write lock for all DB mutations (Lesson #1335) ---
_write_lock = threading.Lock()

# --- Stats buffering ---
_stats_buffer: list[tuple[int, float | None, str | None]] = []
_stats_buffer_lock = threading.Lock()
_STATS_FLUSH_THRESHOLD = 30
_STATS_FLUSH_INTERVAL = 300  # 5 minutes
_MAX_STATS_BUFFER = 500  # Cap to prevent OOM on persistent DB errors
_stats_last_flush: float = time.monotonic()
_flush_timer: threading.Timer | None = None

# --- Periodic WAL checkpoint ---
_WAL_CHECKPOINT_INTERVAL = 1800  # 30 minutes
_last_wal_checkpoint: float = time.monotonic()

# --- Double-init guard ---
_db_initialized: bool = False

# --- Schema version ---
CURRENT_SCHEMA_VERSION = 2

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
    quarantine_reason TEXT,
    dhash TEXT
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
CREATE INDEX IF NOT EXISTS idx_photos_dhash ON photos(dhash);
"""

# --- Smart albums (computed queries) ---

# WARNING: Values are interpolated into SQL queries — must NEVER come from user input.
# These are constants defining smart album filter clauses.
SMART_ALBUMS: dict[str, dict[str, Any]] = {
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


def _db_path() -> Path:
    """Return the Path to the FrameCast database file."""
    return Path(media.get_media_dir()) / "framecast.db"


def get_db() -> sqlite3.Connection:
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


def init_db() -> None:
    """Create tables, indices, and run migrations if needed.

    Safe to call multiple times (idempotent).
    """
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _write_lock:
        with closing(get_db()) as conn:
            # Enable incremental auto-vacuum before creating tables.
            # Must be set before any tables exist on a new database;
            # on an existing DB this is a no-op (requires VACUUM to switch).
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            conn.executescript(_SCHEMA_SQL)
            conn.executescript(_INDEX_SQL)

            # FTS5 virtual table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
                    filename, tags, album_names,
                    content='', content_rowid='id'
                )
            """)

            # Check schema version
            row = conn.execute(
                "SELECT MAX(version) AS v FROM schema_version"
            ).fetchone()
            current = row["v"] if row and row["v"] is not None else 0

            if current < CURRENT_SCHEMA_VERSION:
                # Run schema migrations for each version step
                if current < 1:
                    # v0 -> v1: import existing media files into DB
                    migrate_from_files(conn)
                if current < 2:
                    # v1 -> v2: add perceptual hash column for duplicate detection
                    _migrate_v2_dhash(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (CURRENT_SCHEMA_VERSION,),
                )
                conn.commit()
                # WAL checkpoint after migration
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            else:
                conn.commit()

    # Auto-prune quarantined photos older than 30 days
    prune_quarantined()

    global _db_initialized
    if not _db_initialized:
        _prune_old_stats()
        atexit.register(_shutdown_db)
        _start_flush_timer()
        _db_initialized = True

    # Build FTS index from existing data
    rebuild_fts()

    log.info("DATABASE: INITIALIZED at %s", db_path)


def vacuum_if_needed() -> None:
    """Run incremental vacuum to reclaim space from deleted photos.

    Uses PRAGMA incremental_vacuum which is lighter than full VACUUM
    and safe to run while the app is serving requests (WAL mode).
    Only runs if there are freelist pages to reclaim.
    """
    try:
        with closing(get_db()) as conn:
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
            if freelist > 0:
                conn.execute("PRAGMA incremental_vacuum(100)")
                log.info("Incremental vacuum reclaimed up to 100 pages (freelist was %d)", freelist)
    except Exception:
        log.warning("Incremental vacuum failed", exc_info=True)


# --- Photo CRUD ---


def insert_photo(
    filename: str,
    filepath: str,
    mime_type: str | None = None,
    file_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    is_video: bool = False,
    checksum_sha256: str | None = None,
    thumbnail_path: str | None = None,
    gps_lat: float | None = None,
    gps_lon: float | None = None,
    exif_date: str | None = None,
    uploaded_by: str = "default",
    quarantined: bool = False,
    quarantine_reason: str | None = None,
) -> int | None:
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
            # Index in FTS (non-quarantined photos only)
            photo_id = cur.lastrowid
            if not quarantined:
                _fts_index_photo(conn, photo_id)
            conn.commit()
            return photo_id


def get_photo_by_checksum(checksum: str) -> dict[str, Any] | None:
    """Return a photo row matching the SHA256, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE checksum_sha256 = ?", (checksum,)
        ).fetchone()
        return dict(row) if row else None


def get_photo_by_id(photo_id: int) -> dict[str, Any] | None:
    """Return a photo row by id, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
        return dict(row) if row else None


def get_photo_by_filename(filename: str) -> dict[str, Any] | None:
    """Return a photo row by filename, or None."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None


def get_photos(
    favorite_only: bool = False,
    include_hidden: bool = False,
    user: str | None = None,
    album_id: int | None = None,
    quarantined: bool = False,
) -> list[dict[str, Any]]:
    """SELECT photos with optional filters.

    Returns a list of dicts.
    """
    conditions: list[str] = []
    params: list[Any] = []

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


def get_playlist_candidates() -> list[dict[str, Any]]:
    """Get all non-quarantined, non-hidden photos for slideshow rotation."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT id, filename, uploaded_at, exif_date, is_favorite, view_count
               FROM photos WHERE quarantined = 0 AND is_hidden = 0"""
        ).fetchall()
        return [dict(r) for r in rows]


def update_photo_quarantine(photo_id: int, quarantined: bool, reason: str | None = None) -> None:
    """Set quarantine status for a photo."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET quarantined = ?, quarantine_reason = ? WHERE id = ?",
                (1 if quarantined else 0, reason, photo_id),
            )
            # Update FTS: remove when quarantining, add when restoring
            if quarantined:
                _fts_remove_photo(conn, photo_id)
            else:
                _fts_index_photo(conn, photo_id)
            conn.commit()


def toggle_favorite(photo_id: int) -> bool | None:
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


def toggle_hidden(photo_id: int) -> bool | None:
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


def unquarantine_photo(
    photo_id: int,
    file_size: int,
    width: int | None,
    height: int | None,
    checksum: str,
    gps_lat: float | None,
    gps_lon: float | None,
    dhash: str | None = None,
) -> None:
    """Clear quarantine and update metadata after successful upload processing."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                """UPDATE photos SET quarantined = 0, quarantine_reason = NULL,
                   file_size = ?, width = ?, height = ?,
                   checksum_sha256 = ?, gps_lat = ?, gps_lon = ?,
                   dhash = ?
                   WHERE id = ?""",
                (file_size, width, height, checksum, gps_lat, gps_lon, dhash, photo_id),
            )
            # Photo is now visible — add to FTS index
            _fts_index_photo(conn, photo_id)
            conn.commit()


def find_near_duplicates(dhash: str | None, threshold: int = 10) -> list[dict[str, Any]]:
    """Find photos with dhash within Hamming distance threshold.

    Returns list of photo dicts that are potential duplicates.
    Uses in-Python comparison (fast enough for <10k photos).
    """
    if not dhash:
        return []
    from .media import hamming_distance
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM photos WHERE dhash IS NOT NULL AND quarantined = 0"
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            dist = hamming_distance(dhash, row["dhash"])
            if dist <= threshold:
                d = dict(row)
                d["distance"] = dist
                results.append(d)
        return results


def bulk_quarantine_all(reason: str = "bulk delete") -> None:
    """Mark all non-quarantined photos as quarantined."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "UPDATE photos SET quarantined = 1, quarantine_reason = ? "
                "WHERE quarantined = 0",
                (reason,),
            )
            conn.commit()


def delete_photo(photo_id: int) -> None:
    """Mark a photo as quarantined (soft delete)."""
    update_photo_quarantine(photo_id, True, reason="deleted by user")


def delete_photos_by_ids(photo_ids: list[int]) -> int:
    """Hard-delete photo records by ID list. Returns count deleted.

    Used after files have already been unlinked (C15 — disk-full recovery).
    Cascades to album_photos, photo_tags, display_stats via FK ON DELETE CASCADE.
    """
    if not photo_ids:
        return 0
    placeholders = ",".join("?" * len(photo_ids))
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                f"DELETE FROM photos WHERE id IN ({placeholders})",
                photo_ids,
            )
            conn.commit()
            return cur.rowcount


# --- Album CRUD ---


def create_album(name: str, description: str | None = None) -> int | None:
    """Create a new album. Returns the album id."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "INSERT INTO albums (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
            return cur.lastrowid


def get_albums() -> list[dict[str, Any]]:
    """Return all albums as a list of dicts, including photo_count and cover_filename."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT a.*,
                      (SELECT COUNT(*) FROM album_photos ap WHERE ap.album_id = a.id) AS photo_count,
                      p.filename AS cover_filename
               FROM albums a
               LEFT JOIN photos p ON p.id = a.cover_photo_id
               ORDER BY a.sort_order, a.name"""
        ).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            album = dict(r)
            # If no explicit cover photo but album has photos, use the first one
            if not album.get("cover_photo_id") and album.get("photo_count", 0) > 0:
                first = conn.execute(
                    """SELECT p.id, p.filename FROM photos p
                       JOIN album_photos ap ON p.id = ap.photo_id
                       WHERE ap.album_id = ?
                       ORDER BY ap.added_at DESC LIMIT 1""",
                    (album["id"],),
                ).fetchone()
                if first:
                    album["cover_photo_id"] = first["id"]
                    album["cover_filename"] = first["filename"]
            result.append(album)
        return result


def delete_album(album_id: int) -> None:
    """Delete an album by id."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
            conn.commit()


def add_to_album(photo_id: int, album_id: int) -> None:
    """Add a photo to an album. Ignores duplicates."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO album_photos (album_id, photo_id) VALUES (?, ?)",
                (album_id, photo_id),
            )
            conn.commit()


def remove_from_album(photo_id: int, album_id: int) -> None:
    """Remove a photo from an album."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM album_photos WHERE album_id = ? AND photo_id = ?",
                (album_id, photo_id),
            )
            conn.commit()


def get_album_photos(album_id: int) -> list[dict[str, Any]]:
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


def add_tag(photo_id: int, tag_name: str) -> int | None:
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
                tag_id: int = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO tags (name) VALUES (?)", (tag_name,)
                )
                tag_id = cur.lastrowid  # type: ignore[assignment]

            conn.execute(
                "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?)",
                (photo_id, tag_id),
            )
            conn.commit()
            return tag_id


def remove_tag(photo_id: int, tag_id: int) -> None:
    """Remove a tag from a photo."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM photo_tags WHERE photo_id = ? AND tag_id = ?",
                (photo_id, tag_id),
            )
            conn.commit()


def get_tags(photo_id: int) -> list[dict[str, Any]]:
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


def get_all_tags() -> list[dict[str, Any]]:
    """Return all tags in the system (for autocomplete)."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, name FROM tags ORDER BY name LIMIT 500"
        ).fetchall()
        return [dict(r) for r in rows]


# --- User CRUD ---


def create_user(name: str, is_admin: bool = False) -> int | None:
    """Create a new user. Returns the user id."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "INSERT INTO users (name, is_admin) VALUES (?, ?)",
                (name, 1 if is_admin else 0),
            )
            conn.commit()
            return cur.lastrowid


def get_users() -> list[dict[str, Any]]:
    """Return all users as a list of dicts."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def get_or_create_user(name: str, is_admin: bool = False) -> int | None:
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


def create_user_returning_row(name: str) -> dict[str, Any] | None:
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


def delete_user_reassign(user_id: int) -> None:
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


def record_view(photo_id: int, duration: float | None = None, transition: str | None = None) -> None:
    """Buffer a display stat entry. Flushes on threshold or timer."""
    global _stats_last_flush
    entry = (photo_id, duration, transition)
    with _stats_buffer_lock:
        _stats_buffer.append(entry)
        count = len(_stats_buffer)

    if count >= _STATS_FLUSH_THRESHOLD:
        _flush_stats()


def _flush_stats() -> None:
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


def _shutdown_db() -> None:
    """Flush stats and checkpoint WAL on clean shutdown."""
    _flush_stats()
    try:
        with closing(get_db()) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log.info("DATABASE: clean shutdown — WAL checkpointed")
    except Exception as exc:
        log.error("DATABASE: WAL checkpoint on shutdown failed: %s", exc)


def _periodic_flush() -> None:
    """Called by timer thread to flush stats and run periodic WAL checkpoint."""
    global _last_wal_checkpoint
    try:
        _flush_stats()
    except Exception as exc:
        log.error("STATS: periodic flush error: %s", exc)
    # Passive WAL checkpoint every 30 minutes (R — prevents unbounded WAL growth)
    now = time.monotonic()
    if now - _last_wal_checkpoint >= _WAL_CHECKPOINT_INTERVAL:
        try:
            with closing(get_db()) as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            _last_wal_checkpoint = now
            log.debug("DATABASE: periodic WAL checkpoint (PASSIVE)")
        except Exception as exc:
            log.warning("DATABASE: periodic WAL checkpoint failed: %s", exc)
    _start_flush_timer()


_flush_timer_lock = threading.Lock()


def _start_flush_timer() -> None:
    """Start the periodic stats flush timer."""
    global _flush_timer
    with _flush_timer_lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
        _flush_timer = threading.Timer(_STATS_FLUSH_INTERVAL, _periodic_flush)
        _flush_timer.daemon = True
        _flush_timer.start()


def register_shutdown_flush() -> None:
    """Register signal handlers to flush stats buffer on graceful shutdown.

    Prevents stat loss when systemd sends SIGTERM (up to 5min of buffered data).
    """
    import signal
    import types

    def _shutdown_flush(signum: int, frame: types.FrameType | None) -> None:
        if _stats_buffer:
            log.info("Flushing %d buffered stats on signal %d", len(_stats_buffer), signum)
            _flush_stats()

    signal.signal(signal.SIGTERM, _shutdown_flush)
    signal.signal(signal.SIGINT, _shutdown_flush)


def _prune_old_stats() -> None:
    """DELETE display_stats older than 30 days."""
    with _write_lock:
        with closing(get_db()) as conn:
            cur = conn.execute(
                "DELETE FROM display_stats WHERE shown_at < datetime('now', '-30 days')"
            )
            conn.commit()
            if cur.rowcount > 0:
                log.info("STATS: PRUNED %d entries older than 30 days", cur.rowcount)


def prune_quarantined(days: int = 30) -> int:
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


def get_stats() -> dict[str, Any]:
    """Return aggregated display and content stats."""
    with closing(get_db()) as conn:
        total: int = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE quarantined = 0"
        ).fetchone()["c"]
        favorites: int = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE is_favorite = 1 AND quarantined = 0"
        ).fetchone()["c"]
        hidden: int = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE is_hidden = 1 AND quarantined = 0"
        ).fetchone()["c"]
        videos: int = conn.execute(
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

        total_views: int = conn.execute(
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


def get_smart_album_photos(smart_key: str) -> list[dict[str, Any]]:
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


# --- Full-text search (FTS5) ---


def rebuild_fts() -> None:
    """Rebuild the FTS5 index from current photo data."""
    with _write_lock:
        with closing(get_db()) as conn:
            try:
                conn.execute("DELETE FROM photos_fts")
                conn.execute("""
                    INSERT INTO photos_fts(rowid, filename, tags, album_names)
                    SELECT p.id,
                           p.filename,
                           COALESCE((SELECT GROUP_CONCAT(t.name, ' ')
                                     FROM photo_tags pt JOIN tags t ON t.id = pt.tag_id
                                     WHERE pt.photo_id = p.id), ''),
                           COALESCE((SELECT GROUP_CONCAT(a.name, ' ')
                                     FROM album_photos ap JOIN albums a ON a.id = ap.album_id
                                     WHERE ap.photo_id = p.id), '')
                    FROM photos p
                    WHERE p.quarantined = 0
                """)
                conn.commit()
                log.info("FTS: INDEX REBUILT")
            except Exception:
                log.error("FTS: rebuild failed", exc_info=True)


def _fts_index_photo(conn: sqlite3.Connection, photo_id: int | None) -> None:
    """Add or update a single photo in the FTS index (caller holds _write_lock)."""
    try:
        conn.execute(
            "INSERT INTO photos_fts(photos_fts, rowid, filename, tags, album_names) "
            "VALUES('delete', ?, '', '', '')",
            (photo_id,),
        )
    except Exception:
        pass  # Row may not exist in FTS yet
    try:
        conn.execute("""
            INSERT INTO photos_fts(rowid, filename, tags, album_names)
            SELECT p.id,
                   p.filename,
                   COALESCE((SELECT GROUP_CONCAT(t.name, ' ')
                             FROM photo_tags pt JOIN tags t ON t.id = pt.tag_id
                             WHERE pt.photo_id = p.id), ''),
                   COALESCE((SELECT GROUP_CONCAT(a.name, ' ')
                             FROM album_photos ap JOIN albums a ON a.id = ap.album_id
                             WHERE ap.photo_id = p.id), '')
            FROM photos p
            WHERE p.id = ? AND p.quarantined = 0
        """, (photo_id,))
    except Exception:
        log.warning("FTS: index update failed for photo %d", photo_id, exc_info=True)


def _fts_remove_photo(conn: sqlite3.Connection, photo_id: int) -> None:
    """Remove a photo from the FTS index (caller holds _write_lock)."""
    try:
        conn.execute(
            "INSERT INTO photos_fts(photos_fts, rowid, filename, tags, album_names) "
            "VALUES('delete', ?, '', '', '')",
            (photo_id,),
        )
    except Exception:
        log.warning("FTS: remove failed for photo %d", photo_id, exc_info=True)


def search_photos(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search photos using FTS5. Returns list of photo dicts."""
    if not query or not query.strip():
        return []
    safe_q = query.strip().replace('"', '""')
    fts_query = f'"{safe_q}"*'
    try:
        with closing(get_db()) as conn:
            rows = conn.execute("""
                SELECT p.* FROM photos p
                JOIN photos_fts fts ON fts.rowid = p.id
                WHERE photos_fts MATCH ? AND p.quarantined = 0
                ORDER BY rank
                LIMIT ?
            """, (fts_query, limit)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        log.warning("FTS: search failed for query %r", query, exc_info=True)
        return []


# --- Backup ---


def backup_db() -> str:
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


def restore_db(uploaded_path: str | Path) -> bool:
    """Restore database from an uploaded backup file.

    Validates the file is a valid SQLite database with expected tables
    before replacing the current database.

    Returns True on success, raises ValueError on validation failure.
    """
    # Validate it's a real SQLite database
    try:
        with closing(sqlite3.connect(str(uploaded_path))) as test_conn:
            test_conn.row_factory = sqlite3.Row
            # Check for required tables
            tables = {row["name"] for row in test_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            required = {"photos", "albums", "tags", "users"}
            missing = required - tables
            if missing:
                raise ValueError(
                    f"Missing required tables: {', '.join(sorted(missing))}"
                )
            # Quick sanity: can we read from photos?
            test_conn.execute("SELECT COUNT(*) FROM photos").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Invalid SQLite database: {exc}") from exc

    # Backup current DB first (safety net)
    current_path = _db_path()
    safety_backup = str(current_path) + ".pre-restore"
    if current_path.exists():
        shutil.copy2(str(current_path), safety_backup)
        log.info("Pre-restore safety backup: %s", safety_backup)

    # Atomic restore: copy to temp, fsync, rename (C14 — prevents truncation on power loss)
    with _write_lock:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(current_path.parent), suffix=".db.tmp")
        try:
            shutil.copy2(str(uploaded_path), tmp_path)
            os.fsync(tmp_fd)
            os.close(tmp_fd)
            tmp_fd = -1
            os.replace(tmp_path, str(current_path))
        except Exception:
            if tmp_fd >= 0:
                os.close(tmp_fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        log.info("Database restored from uploaded backup (atomic)")

    return True


# --- WAL checkpoint (periodic) ---


def wal_checkpoint() -> None:
    """Run WAL checkpoint to reclaim space."""
    with closing(get_db()) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    log.info("DATABASE: WAL CHECKPOINT COMPLETE")


# --- Schema migrations ---


def _migrate_v2_dhash(conn: sqlite3.Connection) -> None:
    """v1 -> v2: Add dhash column for perceptual duplicate detection.

    Uses ALTER TABLE for existing databases. The column already exists
    in _SCHEMA_SQL for new databases, so this is safe to run either way
    (SQLite silently errors on duplicate ADD COLUMN, which we catch).
    """
    try:
        conn.execute("ALTER TABLE photos ADD COLUMN dhash TEXT")
        log.info("MIGRATION v2: Added dhash column to photos table")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            log.debug("MIGRATION v2: dhash column already exists")
        else:
            raise
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_dhash ON photos(dhash)")
    log.info("MIGRATION v2: dhash index created")


# --- Migration from files ---


def _compute_sha256(filepath: str | Path) -> str:
    """Compute SHA256 hash of a file."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


# Public alias for external callers (web_upload.py etc.)
compute_sha256 = _compute_sha256


_pillow_warned: bool = False


def _extract_exif_date(filepath: str | Path) -> str | None:
    """Extract the EXIF date from an image file, or None."""
    global _pillow_warned
    try:
        from PIL import Image as PILImage
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


def _get_image_dimensions(filepath: str | Path) -> tuple[int | None, int | None]:
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


def _migrate_impl(conn: sqlite3.Connection) -> None:
    """Core migration logic — scan MEDIA_DIR and import files into the database.

    Called by migrate_from_files with a valid connection.
    """
    media_dir = Path(media.get_media_dir())
    if not media_dir.exists():
        log.info("MIGRATION: MEDIA_DIR does not exist, skipping")
        return

    # Ensure default user exists
    existing = conn.execute(
        "SELECT id FROM users WHERE name = 'default'"
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (name, is_admin) VALUES ('default', 1)"
        )

    # Load existing GPS cache
    gps_cache: dict[str, Any] = {}
    cache_path = media_dir / ".locations.json"
    if cache_path.exists():
        try:
            import json
            with open(cache_path, "r", encoding="utf-8") as cache_fh:
                gps_cache = json.load(cache_fh)
        except Exception as exc:
            log.warning("MIGRATION: Failed to load GPS cache: %s", exc)

    # Gather media files
    image_ext, video_ext = media.get_allowed_extensions()
    all_ext = image_ext | video_ext
    skip_dirs = {media_dir / "thumbnails", media_dir / "quarantine"}

    media_files: list[Path] = []
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
        width: int | None = None
        height: int | None = None
        exif_date: str | None = None
        gps_lat: float | None = None
        gps_lon: float | None = None

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
        thumb_path: str | None = None
        if is_vid:
            thumb_file = media_dir / "thumbnails" / (filepath.stem + ".jpg")
            if thumb_file.exists():
                thumb_path = str(thumb_file)

        # Determine MIME type
        mime_map: dict[str, str] = {
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


def migrate_from_files(conn: sqlite3.Connection | None = None) -> None:
    """Scan MEDIA_DIR for media files and import them into the database.

    Reads existing GPS JSON cache and merges coordinates into photo rows.
    Creates a 'default' user. Idempotent: skips files already in DB.

    Args:
        conn: An existing DB connection (used during init_db). If None,
              opens a new connection.
    """
    if conn is None:
        with closing(get_db()) as new_conn:
            _migrate_impl(new_conn)
        return
    _migrate_impl(conn)
