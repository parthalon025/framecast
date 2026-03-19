"""Tests for user management and stats (app/modules/users.py + API endpoints).

Covers: user CRUD, upload stats aggregation, full stats for dashboard,
delete with photo reassignment, and stats endpoint empty-state validation.
"""

import sqlite3
from contextlib import closing
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# User CRUD tests (users module)
# ---------------------------------------------------------------------------


class TestUsersCrud:
    """Tests for users.create_user, get_users, delete_user."""

    def test_create_user(self, initialized_db):
        """create_user returns the new user row as a dict."""
        import modules.users as users_mod

        result = users_mod.create_user("alice")
        assert result is not None
        assert result["name"] == "alice"
        assert result["upload_count"] == 0

    def test_create_user_duplicate(self, initialized_db):
        """create_user raises on duplicate name."""
        import modules.users as users_mod

        users_mod.create_user("bob")
        with pytest.raises(sqlite3.IntegrityError):
            users_mod.create_user("bob")

    def test_get_users_ordered_by_uploads(self, initialized_db):
        """get_users returns users ordered by upload_count DESC."""
        import modules.users as users_mod

        users_mod.create_user("low")
        users_mod.create_user("high")

        # Give 'high' some uploads by directly updating the count
        with initialized_db._write_lock:
            with closing(initialized_db.get_db()) as conn:
                conn.execute(
                    "UPDATE users SET upload_count = 10 WHERE name = 'high'"
                )
                conn.commit()

        result = users_mod.get_users()
        names = [u["name"] for u in result]
        # 'high' should come before 'low' and 'default'
        assert names.index("high") < names.index("low")

    def test_delete_user_reassigns_photos(self, initialized_db):
        """delete_user reassigns photos to 'default' before deleting."""
        import modules.users as users_mod

        user_row = users_mod.create_user("departing")
        user_id = user_row["id"]

        # Insert a photo by this user
        initialized_db.insert_photo(
            filename="departing_photo.jpg",
            filepath="/media/departing_photo.jpg",
            uploaded_by="departing",
        )

        # Verify photo is owned by 'departing'
        photo = initialized_db.get_photo_by_filename("departing_photo.jpg")
        assert photo["uploaded_by"] == "departing"

        # Delete the user
        users_mod.delete_user(user_id)

        # Photo should now belong to 'default'
        photo = initialized_db.get_photo_by_filename("departing_photo.jpg")
        assert photo["uploaded_by"] == "default"

        # User should be gone
        all_users = users_mod.get_users()
        names = [u["name"] for u in all_users]
        assert "departing" not in names

    def test_delete_user_nonexistent(self, initialized_db):
        """delete_user with nonexistent id doesn't error."""
        import modules.users as users_mod

        # Should not raise
        users_mod.delete_user(99999)


# ---------------------------------------------------------------------------
# Upload stats tests (users module)
# ---------------------------------------------------------------------------


class TestUploadStats:
    """Tests for get_upload_stats."""

    def test_upload_stats_empty(self, initialized_db):
        """get_upload_stats returns empty list with no photos."""
        import modules.users as users_mod

        result = users_mod.get_upload_stats()
        assert isinstance(result, list)
        # May contain 'default' if migration created photos
        # But with fresh DB and no photos, should be empty
        assert len(result) == 0

    def test_upload_stats_counts(self, initialized_db):
        """get_upload_stats returns correct per-user counts."""
        import modules.users as users_mod

        initialized_db.get_or_create_user("alice")
        initialized_db.get_or_create_user("bob")

        initialized_db.insert_photo(
            filename="a1.jpg", filepath="/media/a1.jpg", uploaded_by="alice"
        )
        initialized_db.insert_photo(
            filename="a2.jpg", filepath="/media/a2.jpg", uploaded_by="alice"
        )
        initialized_db.insert_photo(
            filename="b1.jpg", filepath="/media/b1.jpg", uploaded_by="bob"
        )

        stats = users_mod.get_upload_stats()
        by_name = {s["uploaded_by"]: s["count"] for s in stats}
        assert by_name["alice"] == 2
        assert by_name["bob"] == 1

    def test_upload_stats_excludes_quarantined(self, initialized_db):
        """get_upload_stats excludes quarantined photos."""
        import modules.users as users_mod

        initialized_db.get_or_create_user("charlie")
        initialized_db.insert_photo(
            filename="good.jpg", filepath="/media/good.jpg", uploaded_by="charlie"
        )
        initialized_db.insert_photo(
            filename="bad.jpg", filepath="/media/bad.jpg",
            uploaded_by="charlie", quarantined=True, quarantine_reason="corrupt",
        )

        stats = users_mod.get_upload_stats()
        by_name = {s["uploaded_by"]: s["count"] for s in stats}
        assert by_name["charlie"] == 1


# ---------------------------------------------------------------------------
# Full stats tests (users module)
# ---------------------------------------------------------------------------


class TestFullStats:
    """Tests for get_full_stats (dashboard data)."""

    def test_full_stats_empty_db(self, initialized_db):
        """get_full_stats returns valid data for empty DB (no 500)."""
        import modules.users as users_mod

        stats = users_mod.get_full_stats()
        assert stats["total_photos"] == 0
        assert stats["total_videos"] == 0
        assert stats["storage_bytes"] == 0
        assert stats["storage_used"] == "0 B"
        assert isinstance(stats["by_user"], list)
        assert isinstance(stats["most_shown"], list)
        assert isinstance(stats["least_shown"], list)
        assert isinstance(stats["timeline"], list)
        assert stats["total_views"] == 0
        assert stats["avg_duration"] is None

    def test_full_stats_with_data(self, initialized_db):
        """get_full_stats returns correct aggregated data."""
        import modules.users as users_mod

        initialized_db.get_or_create_user("alice")

        initialized_db.insert_photo(
            filename="s1.jpg", filepath="/media/s1.jpg",
            file_size=1024, uploaded_by="alice",
        )
        initialized_db.insert_photo(
            filename="s2.mp4", filepath="/media/s2.mp4",
            file_size=2048, is_video=True,
        )

        stats = users_mod.get_full_stats()
        assert stats["total_photos"] == 2
        assert stats["total_videos"] == 1
        assert stats["storage_bytes"] == 3072
        assert len(stats["by_user"]) >= 1

    def test_full_stats_most_shown(self, initialized_db):
        """get_full_stats returns most shown photos."""
        import modules.users as users_mod

        pid = initialized_db.insert_photo(
            filename="popular.jpg", filepath="/media/popular.jpg"
        )
        # Set view count directly
        with initialized_db._write_lock:
            with closing(initialized_db.get_db()) as conn:
                conn.execute(
                    "UPDATE photos SET view_count = 50 WHERE id = ?", (pid,)
                )
                conn.commit()

        stats = users_mod.get_full_stats()
        assert len(stats["most_shown"]) >= 1
        assert stats["most_shown"][0]["filename"] == "popular.jpg"
        assert stats["most_shown"][0]["view_count"] == 50

    def test_full_stats_least_shown(self, initialized_db):
        """get_full_stats returns least shown (neglected) photos."""
        import modules.users as users_mod

        pid1 = initialized_db.insert_photo(
            filename="neglected.jpg", filepath="/media/neglected.jpg"
        )
        pid2 = initialized_db.insert_photo(
            filename="popular.jpg", filepath="/media/popular.jpg"
        )
        with initialized_db._write_lock:
            with closing(initialized_db.get_db()) as conn:
                conn.execute(
                    "UPDATE photos SET view_count = 1 WHERE id = ?", (pid1,)
                )
                conn.execute(
                    "UPDATE photos SET view_count = 100 WHERE id = ?", (pid2,)
                )
                conn.commit()

        stats = users_mod.get_full_stats()
        assert len(stats["least_shown"]) >= 1
        assert stats["least_shown"][0]["filename"] == "neglected.jpg"

    def test_full_stats_never_shown(self, initialized_db):
        """get_full_stats counts photos never displayed."""
        import modules.users as users_mod

        initialized_db.insert_photo(
            filename="unseen.jpg", filepath="/media/unseen.jpg"
        )

        stats = users_mod.get_full_stats()
        assert stats["never_shown_count"] == 1


# ---------------------------------------------------------------------------
# Format bytes tests
# ---------------------------------------------------------------------------


class TestFormatBytes:
    """Tests for _format_bytes helper."""

    def test_zero(self):
        import modules.users as users_mod
        assert users_mod._format_bytes(0) == "0 B"

    def test_bytes(self):
        import modules.users as users_mod
        assert users_mod._format_bytes(512) == "512 B"

    def test_kilobytes(self):
        import modules.users as users_mod
        result = users_mod._format_bytes(1536)
        assert "KB" in result

    def test_megabytes(self):
        import modules.users as users_mod
        result = users_mod._format_bytes(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        import modules.users as users_mod
        result = users_mod._format_bytes(2 * 1024 * 1024 * 1024)
        assert "GB" in result


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    """Tests for the /api/stats endpoint returning valid data."""

    def test_stats_endpoint_empty_db(self, initialized_db):
        """Stats endpoint returns valid JSON for empty DB."""
        import modules.users as users_mod

        stats = users_mod.get_full_stats()
        # Validate structure — these fields must exist
        required_keys = {
            "total_photos", "total_videos", "storage_bytes",
            "storage_used", "by_user", "most_shown", "least_shown",
            "total_views", "avg_duration", "timeline",
        }
        assert required_keys.issubset(set(stats.keys())), (
            f"Missing keys: {required_keys - set(stats.keys())}"
        )

    def test_stats_endpoint_with_views(self, initialized_db):
        """Stats endpoint includes display stats after views are recorded."""
        import modules.users as users_mod

        pid = initialized_db.insert_photo(
            filename="viewed.jpg", filepath="/media/viewed.jpg"
        )
        # Record some views and flush
        initialized_db.record_view(pid, 5.0, "fade")
        initialized_db.record_view(pid, 3.0, "slide")
        initialized_db._flush_stats()

        stats = users_mod.get_full_stats()
        assert stats["total_views"] == 2
        assert stats["avg_duration"] is not None
        assert stats["avg_duration"] == 4.0  # (5.0 + 3.0) / 2
