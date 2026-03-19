"""Tests for the weighted rotation and playlist generation (app/modules/rotation.py).

Covers: weighted distribution, diversity penalty, "on this day" logic,
empty library handling, and playlist size parameter.
"""

import os
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
from unittest import mock

import pytest

# Patch config and media before importing rotation/db
_test_media_dir = None


def _fake_get(key, default=""):
    """Fake config.get that returns test-safe values."""
    if key == "MEDIA_DIR":
        return str(_test_media_dir)
    if key == "IMAGE_EXTENSIONS":
        return ".jpg,.jpeg,.png,.gif,.webp,.tiff"
    if key == "VIDEO_EXTENSIONS":
        return ".mp4,.mkv,.avi,.mov"
    return default


@pytest.fixture(autouse=True)
def isolated_media_dir(tmp_path, monkeypatch):
    """Create a fresh temporary MEDIA_DIR for each test."""
    global _test_media_dir
    _test_media_dir = tmp_path / "media"
    _test_media_dir.mkdir()

    monkeypatch.setattr("modules.config.get", _fake_get)
    monkeypatch.setattr("modules.media.get_media_dir", lambda: str(_test_media_dir))

    # Reset db module state
    import modules.db as db_mod
    db_mod._stats_buffer.clear()
    if db_mod._flush_timer is not None:
        db_mod._flush_timer.cancel()
        db_mod._flush_timer = None

    yield tmp_path

    if db_mod._flush_timer is not None:
        db_mod._flush_timer.cancel()
        db_mod._flush_timer = None


@pytest.fixture
def db_mod():
    """Return the db module."""
    import modules.db as mod
    return mod


@pytest.fixture
def initialized_db(db_mod):
    """Initialize the database and return the module."""
    with mock.patch.object(db_mod, "_start_flush_timer"):
        db_mod.init_db()
    return db_mod


@pytest.fixture
def rotation_mod():
    """Return the rotation module."""
    import modules.rotation as mod
    return mod


def _insert_photo(db_mod, filename, is_favorite=False, exif_date=None,
                   uploaded_at=None, is_video=False):
    """Helper to insert a photo and return its ID."""
    with closing(db_mod.get_db()) as conn:
        cur = conn.execute(
            """INSERT INTO photos
               (filename, filepath, is_favorite, exif_date, uploaded_at,
                is_video, quarantined, is_hidden, view_count, uploaded_by)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 'default')""",
            (
                filename,
                f"/media/{filename}",
                1 if is_favorite else 0,
                exif_date,
                uploaded_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                1 if is_video else 0,
            ),
        )
        conn.commit()
        return cur.lastrowid


def _record_shown(db_mod, photo_id, count=1):
    """Helper to record a photo as shown in display_stats."""
    with closing(db_mod.get_db()) as conn:
        for _ in range(count):
            conn.execute(
                """INSERT INTO display_stats (photo_id, duration_seconds)
                   VALUES (?, 10.0)""",
                (photo_id,),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Weight computation tests
# ---------------------------------------------------------------------------


class TestComputeWeight:
    """Tests for _compute_weight."""

    def test_base_weight(self, initialized_db, rotation_mod):
        """Non-favorite, old photo, not recently shown has weight 1.0."""
        photo = {
            "id": 1,
            "is_favorite": 0,
            "uploaded_at": "2020-01-01T00:00:00",
        }
        weight = rotation_mod._compute_weight(photo, set())
        assert weight == 1.0

    def test_favorite_boost(self, initialized_db, rotation_mod):
        """Favorite photos get 3x weight."""
        photo = {
            "id": 1,
            "is_favorite": 1,
            "uploaded_at": "2020-01-01T00:00:00",
        }
        weight = rotation_mod._compute_weight(photo, set())
        assert weight == 3.0

    def test_recency_boost_7_days(self, initialized_db, rotation_mod):
        """Photos uploaded within 7 days get 1.5x recency boost."""
        recent = datetime.now() - timedelta(days=2)
        photo = {
            "id": 1,
            "is_favorite": 0,
            "uploaded_at": recent.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        weight = rotation_mod._compute_weight(photo, set())
        assert weight == 1.5

    def test_recency_boost_30_days(self, initialized_db, rotation_mod):
        """Photos uploaded within 30 days get 1.2x recency boost."""
        recent = datetime.now() - timedelta(days=15)
        photo = {
            "id": 1,
            "is_favorite": 0,
            "uploaded_at": recent.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        weight = rotation_mod._compute_weight(photo, set())
        assert weight == 1.2

    def test_diversity_penalty(self, initialized_db, rotation_mod):
        """Recently shown photos get 0.1x penalty."""
        photo = {
            "id": 42,
            "is_favorite": 0,
            "uploaded_at": "2020-01-01T00:00:00",
        }
        weight = rotation_mod._compute_weight(photo, {42})
        assert weight == pytest.approx(0.1)

    def test_favorite_plus_recency(self, initialized_db, rotation_mod):
        """Boosts multiply: favorite (3x) * recent (1.5x) = 4.5."""
        recent = datetime.now() - timedelta(days=2)
        photo = {
            "id": 1,
            "is_favorite": 1,
            "uploaded_at": recent.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        weight = rotation_mod._compute_weight(photo, set())
        assert weight == pytest.approx(4.5)


# ---------------------------------------------------------------------------
# Weighted distribution tests
# ---------------------------------------------------------------------------


class TestWeightedDistribution:
    """Statistical tests for weighted selection bias."""

    def test_favorites_appear_more_often(self, initialized_db, rotation_mod, db_mod):
        """Favorites should appear roughly 3x as often as non-favorites.

        Over 1000 selections, a 3:1 ratio should be statistically detectable.
        We use a generous margin (1.5x-6x) to avoid flaky failures.
        """
        # Create 5 normal + 5 favorite photos (all old enough for no recency boost)
        normal_ids = []
        fav_ids = []
        for i in range(5):
            nid = _insert_photo(db_mod, f"normal_{i}.jpg", is_favorite=False,
                                uploaded_at="2020-01-01T00:00:00")
            normal_ids.append(nid)
            fid = _insert_photo(db_mod, f"fav_{i}.jpg", is_favorite=True,
                                uploaded_at="2020-01-01T00:00:00")
            fav_ids.append(fid)

        all_photos = db_mod.get_photos()
        fav_set = set(fav_ids)

        # Run 1000 weighted selections
        fav_count = 0
        normal_count = 0
        for _ in range(1000):
            selected = rotation_mod._weighted_select(all_photos, set())
            if selected["id"] in fav_set:
                fav_count += 1
            else:
                normal_count += 1

        # Favorites should be selected about 3x more often per photo
        # With 5 fav (weight 3 each = 15) and 5 normal (weight 1 each = 5),
        # expected ratio of fav selections to normal selections is 15:5 = 3:1
        ratio = fav_count / max(normal_count, 1)
        assert 1.5 < ratio < 6.0, (
            f"Favorite ratio {ratio:.2f} outside expected range 1.5-6.0 "
            f"(fav={fav_count}, normal={normal_count})"
        )


# ---------------------------------------------------------------------------
# Diversity tests
# ---------------------------------------------------------------------------


class TestDiversity:
    """Tests for the diversity penalty mechanism."""

    def test_no_immediate_repeat(self, initialized_db, rotation_mod, db_mod):
        """No photo should repeat within 30% of library size when diversity is active."""
        # Create 10 photos
        ids = []
        for i in range(10):
            pid = _insert_photo(db_mod, f"photo_{i}.jpg",
                                uploaded_at="2020-01-01T00:00:00")
            ids.append(pid)

        all_photos = db_mod.get_photos()
        window_size = max(1, int(len(all_photos) * 0.3))  # 3

        # Simulate playlist generation tracking recent IDs
        recent = set()
        selections = []
        for _ in range(10):
            photo = rotation_mod._weighted_select(all_photos, recent)
            selections.append(photo["id"])
            recent.add(photo["id"])
            # Only keep the diversity window
            if len(recent) > window_size:
                # Remove oldest (simulate FIFO, but set doesn't order — the
                # real implementation uses DB query which is naturally ordered)
                pass

        # Within the first window_size selections, all should be unique
        first_window = selections[:window_size]
        assert len(set(first_window)) == len(first_window), (
            f"Repeated photo in diversity window: {first_window}"
        )

    def test_diversity_penalty_reduces_weight(self, initialized_db, rotation_mod):
        """Photos in the recent_shown_ids set get 0.1x weight."""
        photo = {"id": 5, "is_favorite": 0, "uploaded_at": "2020-01-01T00:00:00"}
        normal_weight = rotation_mod._compute_weight(photo, set())
        penalized_weight = rotation_mod._compute_weight(photo, {5})
        assert penalized_weight == pytest.approx(normal_weight * 0.1)


# ---------------------------------------------------------------------------
# On This Day tests
# ---------------------------------------------------------------------------


class TestOnThisDay:
    """Tests for the 'On This Day' feature."""

    def test_matches_month_day_from_prior_year(self, initialized_db, rotation_mod, db_mod):
        """Photos with EXIF date matching today's month-day from a prior year are returned."""
        today = datetime.now()
        # Create a photo from 2 years ago on this day
        past_date = today.replace(year=today.year - 2).strftime("%Y-%m-%dT%H:%M:%S")
        _insert_photo(db_mod, "old_memory.jpg", exif_date=past_date)

        # Create a photo from a different month (should not match)
        other_month = today.replace(month=(today.month % 12) + 1, day=1)
        _insert_photo(db_mod, "other.jpg",
                      exif_date=other_month.strftime("%Y-%m-%dT%H:%M:%S"))

        results = rotation_mod.get_on_this_day()
        assert len(results) == 1
        assert results[0]["filename"] == "old_memory.jpg"
        assert results[0]["on_this_day"] is True
        assert results[0]["years_ago"] == 2

    def test_excludes_same_year(self, initialized_db, rotation_mod, db_mod):
        """Photos from the current year are excluded (not 'memories')."""
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%dT%H:%M:%S")
        _insert_photo(db_mod, "today_upload.jpg", exif_date=today_str)

        results = rotation_mod.get_on_this_day()
        assert len(results) == 0

    def test_falls_back_to_uploaded_at(self, initialized_db, rotation_mod, db_mod):
        """When exif_date is NULL, falls back to uploaded_at for matching."""
        today = datetime.now()
        past_upload = today.replace(year=today.year - 1).strftime("%Y-%m-%dT%H:%M:%S")
        _insert_photo(db_mod, "no_exif.jpg", exif_date=None, uploaded_at=past_upload)

        results = rotation_mod.get_on_this_day()
        assert len(results) == 1
        assert results[0]["filename"] == "no_exif.jpg"
        assert results[0]["years_ago"] == 1

    def test_empty_library_returns_empty(self, initialized_db, rotation_mod):
        """Empty library returns empty list, no errors."""
        results = rotation_mod.get_on_this_day()
        assert results == []


# ---------------------------------------------------------------------------
# Playlist generation tests
# ---------------------------------------------------------------------------


class TestGeneratePlaylist:
    """Tests for generate_playlist."""

    def test_empty_library_returns_empty(self, initialized_db, rotation_mod):
        """Empty photo library returns empty playlist."""
        result = rotation_mod.generate_playlist(count=50)
        assert result["photos"] == []
        assert "playlist_id" in result
        assert len(result["playlist_id"]) == 8

    def test_respects_count_parameter(self, initialized_db, rotation_mod, db_mod):
        """Playlist contains at most `count` photos."""
        for i in range(20):
            _insert_photo(db_mod, f"photo_{i}.jpg",
                          uploaded_at="2020-01-01T00:00:00")

        result = rotation_mod.generate_playlist(count=10)
        assert len(result["photos"]) == 10

    def test_small_library_fills_to_count(self, initialized_db, rotation_mod, db_mod):
        """When library is smaller than count, playlist wraps (allows repeats)."""
        for i in range(3):
            _insert_photo(db_mod, f"photo_{i}.jpg",
                          uploaded_at="2020-01-01T00:00:00")

        result = rotation_mod.generate_playlist(count=10)
        # Should have 10 entries (with repeats since only 3 unique)
        assert len(result["photos"]) == 10

    def test_playlist_has_unique_id(self, initialized_db, rotation_mod, db_mod):
        """Each playlist gets a unique ID."""
        _insert_photo(db_mod, "photo.jpg", uploaded_at="2020-01-01T00:00:00")

        r1 = rotation_mod.generate_playlist()
        r2 = rotation_mod.generate_playlist()
        assert r1["playlist_id"] != r2["playlist_id"]

    def test_on_this_day_included_in_playlist(self, initialized_db, rotation_mod, db_mod):
        """'On This Day' photos are included in the playlist with metadata."""
        today = datetime.now()
        past_date = today.replace(year=today.year - 3).strftime("%Y-%m-%dT%H:%M:%S")
        _insert_photo(db_mod, "memory.jpg", exif_date=past_date)

        # Add some other photos
        for i in range(10):
            _insert_photo(db_mod, f"photo_{i}.jpg",
                          uploaded_at="2020-01-01T00:00:00")

        result = rotation_mod.generate_playlist(count=50)
        otd_photos = [p for p in result["photos"] if p.get("on_this_day")]
        assert len(otd_photos) >= 1
        assert otd_photos[0]["years_ago"] == 3

    def test_excludes_quarantined(self, initialized_db, rotation_mod, db_mod):
        """Quarantined photos are excluded from the playlist."""
        _insert_photo(db_mod, "good.jpg", uploaded_at="2020-01-01T00:00:00")
        bad_id = _insert_photo(db_mod, "bad.jpg",
                               uploaded_at="2020-01-01T00:00:00")
        db_mod.update_photo_quarantine(bad_id, True, reason="corrupt")

        result = rotation_mod.generate_playlist(count=50)
        ids = {p["id"] for p in result["photos"]}
        assert bad_id not in ids

    def test_excludes_hidden(self, initialized_db, rotation_mod, db_mod):
        """Hidden photos are excluded from the playlist."""
        _insert_photo(db_mod, "visible.jpg", uploaded_at="2020-01-01T00:00:00")
        hidden_id = _insert_photo(db_mod, "hidden.jpg",
                                  uploaded_at="2020-01-01T00:00:00")
        db_mod.toggle_hidden(hidden_id)

        result = rotation_mod.generate_playlist(count=50)
        ids = {p["id"] for p in result["photos"]}
        assert hidden_id not in ids
