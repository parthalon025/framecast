"""Weighted photo rotation and playlist generation for FrameCast slideshow.

Implements O(n) per selection with O(log n) lookup via binary CDF search, "On This Day"
memory surfacing, and diversity penalty to prevent photo repetition.

All SQLite access via contextlib.closing() + WAL + busy_timeout (Lesson #34, #1335).
"""

import bisect
import logging
import random
from contextlib import closing
from datetime import datetime, timedelta
from uuid import uuid4

from . import db

log = logging.getLogger(__name__)


def _compute_weight(photo, recent_shown_ids):
    """Compute display weight for a single photo.

    Weight = base * recency_boost * favorite_boost * diversity_penalty

    Args:
        photo: dict with photo columns from DB.
        recent_shown_ids: set of photo IDs shown in the recent window.

    Returns:
        float weight (always > 0).
    """
    base = 1.0

    # Recency boost: newer uploads get more weight
    recency_boost = 1.0
    uploaded_at = photo.get("uploaded_at")
    if uploaded_at:
        try:
            uploaded_dt = datetime.fromisoformat(uploaded_at)
            age = datetime.now() - uploaded_dt
            if age < timedelta(days=7):
                recency_boost = 1.5
            elif age < timedelta(days=30):
                recency_boost = 1.2
        except (ValueError, TypeError):
            log.debug("ROTATION: Failed to parse uploaded_at for photo %d", photo.get("id", 0))

    # Favorite boost
    favorite_boost = 3.0 if photo.get("is_favorite") else 1.0

    # Diversity penalty: reduce weight if recently shown
    diversity_penalty = 0.1 if photo.get("id") in recent_shown_ids else 1.0

    return base * recency_boost * favorite_boost * diversity_penalty


def _weighted_select(photos, recent_shown_ids):
    """Select a single photo using binary CDF search.

    O(log n) selection from weighted distribution.

    Args:
        photos: list of photo dicts.
        recent_shown_ids: set of recently shown photo IDs.

    Returns:
        Selected photo dict.
    """
    if not photos:
        return None
    if len(photos) == 1:
        return photos[0]

    weights = [_compute_weight(p, recent_shown_ids) for p in photos]
    cumulative = []
    total = 0.0
    for w in weights:
        total += w
        cumulative.append(total)

    if total <= 0:
        return random.choice(photos)

    r = random.random() * total
    idx = bisect.bisect_left(cumulative, r)
    return photos[min(idx, len(photos) - 1)]


def get_on_this_day():
    """Return photos whose EXIF date matches today's month-day from a prior year.

    Falls back to uploaded_at if exif_date is NULL.
    Each returned dict gets an ``on_this_day`` flag and ``years_ago`` count.
    """
    try:
        today = datetime.now()
        today_md = today.strftime("%m-%d")
        current_year = today.year

        with closing(db.get_db()) as conn:
            rows = conn.execute(
                """SELECT * FROM photos
                   WHERE quarantined = 0 AND is_hidden = 0
                   AND (
                       (exif_date IS NOT NULL AND strftime('%m-%d', exif_date) = ?)
                       OR
                       (exif_date IS NULL AND strftime('%m-%d', uploaded_at) = ?)
                   )""",
                (today_md, today_md),
            ).fetchall()

        results = []
        for row in rows:
            photo = dict(row)
            # Calculate years ago
            date_str = photo.get("exif_date") or photo.get("uploaded_at")
            years_ago = 0
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace(" ", "T")[:19])
                    years_ago = current_year - dt.year
                except (ValueError, TypeError):
                    log.debug("ROTATION: Failed to parse date for years_ago: %s", date_str)
            # Only include photos from prior years (not today's uploads)
            if years_ago >= 1:
                photo["on_this_day"] = True
                photo["years_ago"] = years_ago
                results.append(photo)

        return results
    except Exception:
        log.error("ROTATION: Failed to query on-this-day photos", exc_info=True)
        return []


def _get_recent_shown_ids(total_photos):
    """Return set of photo IDs shown in the recent diversity window.

    Window size = total_photos * 0.3 (capped to prevent starvation).
    """
    window = max(1, int(total_photos * 0.3))
    try:
        with closing(db.get_db()) as conn:
            rows = conn.execute(
                """SELECT DISTINCT photo_id FROM display_stats
                   ORDER BY shown_at DESC LIMIT ?""",
                (window,),
            ).fetchall()
        return {r["photo_id"] for r in rows}
    except Exception:
        log.error("ROTATION: Failed to query recent shown IDs", exc_info=True)
        return set()


def generate_playlist(count=50):
    """Generate a weighted playlist of photo dicts.

    "On This Day" photos are inserted with priority placement and metadata flag.

    Args:
        count: Number of photos to include in the playlist.

    Returns:
        dict with "photos" (list of photo dicts) and "playlist_id" (str).
    """
    try:
        all_photos = db.get_photos()
    except Exception:
        log.error("ROTATION: Failed to fetch photos for playlist", exc_info=True)
        return {"photos": [], "playlist_id": str(uuid4())[:8]}

    if not all_photos:
        return {"photos": [], "playlist_id": str(uuid4())[:8]}

    recent_shown_ids = _get_recent_shown_ids(len(all_photos))

    # Get "on this day" photos
    otd_photos = get_on_this_day()
    otd_ids = {p["id"] for p in otd_photos}

    # Build the playlist
    playlist = []
    selected_ids = set()

    # Insert "on this day" photos first (they still count toward the total)
    for otd_photo in otd_photos[:min(len(otd_photos), count // 5 or 1)]:
        playlist.append(otd_photo)
        selected_ids.add(otd_photo["id"])

    # Fill remaining slots with weighted selection
    remaining = count - len(playlist)
    # Track IDs we add during this generation to avoid duplicates within the playlist
    for _ in range(remaining):
        if len(selected_ids) >= len(all_photos):
            # All photos exhausted — allow repeats from the full pool
            selected_ids.clear()

        # Temporarily add selected_ids to recent_shown for diversity within playlist
        combined_recent = recent_shown_ids | selected_ids
        photo = _weighted_select(all_photos, combined_recent)
        if photo is None:
            break

        # Mark on_this_day if applicable
        photo_copy = dict(photo)
        if photo_copy["id"] in otd_ids and photo_copy.get("on_this_day") is None:
            otd_match = next((p for p in otd_photos if p["id"] == photo_copy["id"]), None)
            if otd_match:
                photo_copy["on_this_day"] = True
                photo_copy["years_ago"] = otd_match.get("years_ago", 0)

        playlist.append(photo_copy)
        selected_ids.add(photo_copy["id"])

    # Shuffle to distribute OTD photos throughout (not just at the start)
    random.shuffle(playlist)

    return {
        "photos": playlist,
        "playlist_id": str(uuid4())[:8],
    }
