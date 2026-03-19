"""Lightweight user management for FrameCast.

No passwords — just names, upload counts, and stats aggregation.
All DB access goes through the db module's connection helpers and write lock.
"""

import logging
from contextlib import closing

from . import db

log = logging.getLogger(__name__)


def get_users():
    """Return all users ordered by upload count (highest first)."""
    with closing(db.get_db()) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM users ORDER BY upload_count DESC"
        ).fetchall()]


def create_user(name):
    """Create a new user by name. Returns the new user row as a dict.

    Raises sqlite3.IntegrityError if name already exists.
    """
    with db._write_lock:
        with closing(db.get_db()) as conn:
            conn.execute(
                "INSERT INTO users (name) VALUES (?)", (name,)
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM users WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None


def delete_user(user_id):
    """Delete a user by id. Reassigns their photos to 'default'."""
    with db._write_lock:
        with closing(db.get_db()) as conn:
            # Reassign photos to 'default' before deleting the user
            conn.execute(
                "UPDATE photos SET uploaded_by = 'default' "
                "WHERE uploaded_by = (SELECT name FROM users WHERE id = ?)",
                (user_id,),
            )
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
    log.info("USER: DELETED id=%d, photos reassigned to 'default'", user_id)


def get_upload_stats():
    """Return per-user upload stats from the photos table.

    Groups non-quarantined photos by uploaded_by with count and last upload time.
    """
    with closing(db.get_db()) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT uploaded_by, COUNT(*) as count, "
            "MAX(uploaded_at) as last_upload "
            "FROM photos WHERE quarantined = 0 "
            "GROUP BY uploaded_by ORDER BY count DESC"
        ).fetchall()]


def get_full_stats():
    """Return aggregated stats for the dashboard.

    Includes totals, per-user breakdown, most/least shown, and upload timeline.
    """
    with closing(db.get_db()) as conn:
        # Total photos (non-quarantined)
        total_photos = conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE quarantined = 0"
        ).fetchone()["c"]

        # Total videos
        total_videos = conn.execute(
            "SELECT COUNT(*) AS c FROM photos "
            "WHERE quarantined = 0 AND is_video = 1"
        ).fetchone()["c"]

        # Total storage (sum of file_size)
        storage_row = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) AS total "
            "FROM photos WHERE quarantined = 0"
        ).fetchone()
        storage_bytes = storage_row["total"]

        # Photos by user
        by_user = [dict(r) for r in conn.execute(
            "SELECT uploaded_by, COUNT(*) AS count, "
            "MAX(uploaded_at) AS last_upload "
            "FROM photos WHERE quarantined = 0 "
            "GROUP BY uploaded_by ORDER BY count DESC"
        ).fetchall()]

        # Most shown (top 10)
        most_shown = [dict(r) for r in conn.execute(
            "SELECT id, filename, view_count, last_shown_at "
            "FROM photos WHERE quarantined = 0 AND view_count > 0 "
            "ORDER BY view_count DESC LIMIT 10"
        ).fetchall()]

        # Least shown (bottom 10 with at least one view — "NEGLECTED")
        least_shown = [dict(r) for r in conn.execute(
            "SELECT id, filename, view_count, uploaded_at "
            "FROM photos WHERE quarantined = 0 AND view_count > 0 "
            "ORDER BY view_count ASC LIMIT 10"
        ).fetchall()]

        # Never shown (uploaded but view_count = 0)
        never_shown_count = conn.execute(
            "SELECT COUNT(*) AS c FROM photos "
            "WHERE quarantined = 0 AND view_count = 0"
        ).fetchone()["c"]

        # Upload timeline (last 30 days, photos per day)
        timeline = [dict(r) for r in conn.execute(
            "SELECT DATE(uploaded_at) AS date, COUNT(*) AS count "
            "FROM photos WHERE quarantined = 0 "
            "AND uploaded_at >= datetime('now', '-30 days') "
            "GROUP BY DATE(uploaded_at) ORDER BY date"
        ).fetchall()]

        # Total display views
        total_views = conn.execute(
            "SELECT COUNT(*) AS c FROM display_stats"
        ).fetchone()["c"]

        # Average display time
        avg_duration_row = conn.execute(
            "SELECT AVG(duration_seconds) AS avg "
            "FROM display_stats WHERE duration_seconds IS NOT NULL"
        ).fetchone()
        avg_duration = avg_duration_row["avg"]

    return {
        "total_photos": total_photos,
        "total_videos": total_videos,
        "storage_bytes": storage_bytes,
        "storage_used": _format_bytes(storage_bytes),
        "by_user": by_user,
        "most_shown": most_shown,
        "least_shown": least_shown,
        "never_shown_count": never_shown_count,
        "total_views": total_views,
        "avg_duration": round(avg_duration, 1) if avg_duration else None,
        "timeline": timeline,
    }


def _format_bytes(num_bytes):
    """Format bytes into human-readable string with exact values."""
    if num_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(num_bytes)
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[idx]}"
