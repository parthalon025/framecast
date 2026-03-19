"""Tests for the SQLite content model (app/modules/db.py).

Covers: schema creation, WAL mode, CRUD for photos/albums/tags/users,
duplicate detection, stats buffering, migration, and smart albums.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest import mock

import pytest

# Fixtures (isolated_media_dir, db_mod, initialized_db) are in conftest.py


# ---------------------------------------------------------------------------
# Schema and initialization tests
# ---------------------------------------------------------------------------


class TestInitDb:
    """Tests for init_db and schema creation."""

    def test_creates_all_tables(self, initialized_db):
        """init_db creates all expected tables."""
        expected_tables = {
            "photos", "albums", "album_photos", "tags",
            "photo_tags", "users", "display_stats", "schema_version",
        }
        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            table_names = {r["name"] for r in rows}

        assert expected_tables.issubset(table_names), (
            f"Missing tables: {expected_tables - table_names}"
        )

    def test_wal_mode_enabled(self, initialized_db):
        """Database connections use WAL journal mode."""
        with closing(initialized_db.get_db()) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_busy_timeout_set(self, initialized_db):
        """Database connections have busy_timeout configured."""
        with closing(initialized_db.get_db()) as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert timeout == 5000

    def test_foreign_keys_enabled(self, initialized_db):
        """Database connections enforce foreign key constraints."""
        with closing(initialized_db.get_db()) as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1

    def test_schema_version_set(self, initialized_db):
        """init_db sets the schema version."""
        with closing(initialized_db.get_db()) as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM schema_version"
            ).fetchone()
            assert row["v"] == initialized_db.CURRENT_SCHEMA_VERSION

    def test_idempotent(self, initialized_db):
        """Calling init_db twice does not error or duplicate data."""
        with mock.patch.object(initialized_db, "_start_flush_timer"):
            initialized_db.init_db()  # Second call
        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()
            assert rows["c"] >= 1

    def test_indices_created(self, initialized_db):
        """Partial indices are created."""
        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            index_names = {r["name"] for r in rows}

        expected = {
            "idx_photos_favorite", "idx_photos_hidden",
            "idx_photos_uploaded_by", "idx_photos_last_shown",
            "idx_display_stats_photo", "idx_display_stats_shown",
        }
        assert expected.issubset(index_names), (
            f"Missing indices: {expected - index_names}"
        )


# ---------------------------------------------------------------------------
# Photo CRUD tests
# ---------------------------------------------------------------------------


class TestPhotoCrud:
    """Tests for photo insert, query, toggle, hide."""

    def test_insert_and_query(self, initialized_db):
        """Insert a photo and retrieve it."""
        pid = initialized_db.insert_photo(
            filename="test.jpg",
            filepath="/media/test.jpg",
            file_size=1024,
            mime_type="image/jpeg",
        )
        assert pid is not None
        assert pid > 0

        photo = initialized_db.get_photo_by_id(pid)
        assert photo is not None
        assert photo["filename"] == "test.jpg"
        assert photo["file_size"] == 1024
        assert photo["quarantined"] == 0

    def test_get_photos_excludes_quarantined(self, initialized_db):
        """get_photos() excludes quarantined photos by default."""
        initialized_db.insert_photo(
            filename="good.jpg", filepath="/media/good.jpg"
        )
        initialized_db.insert_photo(
            filename="bad.jpg", filepath="/media/bad.jpg",
            quarantined=True, quarantine_reason="corrupt",
        )
        photos = initialized_db.get_photos()
        names = [p["filename"] for p in photos]
        assert "good.jpg" in names
        assert "bad.jpg" not in names

    def test_toggle_favorite(self, initialized_db):
        """toggle_favorite flips the is_favorite flag atomically."""
        pid = initialized_db.insert_photo(
            filename="fav.jpg", filepath="/media/fav.jpg"
        )
        photo = initialized_db.get_photo_by_id(pid)
        assert photo["is_favorite"] == 0

        result = initialized_db.toggle_favorite(pid)
        assert result is True

        result = initialized_db.toggle_favorite(pid)
        assert result is False

    def test_toggle_hidden(self, initialized_db):
        """toggle_hidden flips the is_hidden flag atomically."""
        pid = initialized_db.insert_photo(
            filename="hide.jpg", filepath="/media/hide.jpg"
        )
        result = initialized_db.toggle_hidden(pid)
        assert result is True

        # Hidden photos excluded by default
        photos = initialized_db.get_photos()
        names = [p["filename"] for p in photos]
        assert "hide.jpg" not in names

        # include_hidden=True shows them
        photos = initialized_db.get_photos(include_hidden=True)
        names = [p["filename"] for p in photos]
        assert "hide.jpg" in names

    def test_get_photos_favorite_filter(self, initialized_db):
        """get_photos with favorite_only=True returns only favorites."""
        pid1 = initialized_db.insert_photo(
            filename="a.jpg", filepath="/media/a.jpg"
        )
        initialized_db.insert_photo(
            filename="b.jpg", filepath="/media/b.jpg"
        )
        initialized_db.toggle_favorite(pid1)

        photos = initialized_db.get_photos(favorite_only=True)
        assert len(photos) == 1
        assert photos[0]["filename"] == "a.jpg"

    def test_get_photo_by_filename(self, initialized_db):
        """get_photo_by_filename returns the correct row."""
        initialized_db.insert_photo(
            filename="lookup.png", filepath="/media/lookup.png"
        )
        photo = initialized_db.get_photo_by_filename("lookup.png")
        assert photo is not None
        assert photo["filename"] == "lookup.png"

    def test_get_photo_by_filename_missing(self, initialized_db):
        """get_photo_by_filename returns None for unknown files."""
        photo = initialized_db.get_photo_by_filename("nonexistent.jpg")
        assert photo is None

    def test_delete_photo_soft(self, initialized_db):
        """delete_photo marks as quarantined (soft delete)."""
        pid = initialized_db.insert_photo(
            filename="del.jpg", filepath="/media/del.jpg"
        )
        initialized_db.delete_photo(pid)

        photo = initialized_db.get_photo_by_id(pid)
        assert photo["quarantined"] == 1
        assert photo["quarantine_reason"] == "deleted by user"

    def test_get_photos_user_filter(self, initialized_db):
        """get_photos with user filter returns only that user's photos."""
        initialized_db.get_or_create_user("alice")
        initialized_db.get_or_create_user("bob")
        initialized_db.insert_photo(
            filename="alice1.jpg", filepath="/media/alice1.jpg",
            uploaded_by="alice",
        )
        initialized_db.insert_photo(
            filename="bob1.jpg", filepath="/media/bob1.jpg",
            uploaded_by="bob",
        )
        photos = initialized_db.get_photos(user="alice")
        assert len(photos) == 1
        assert photos[0]["filename"] == "alice1.jpg"


# ---------------------------------------------------------------------------
# Duplicate detection tests
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    """Tests for SHA256-based duplicate detection."""

    def test_duplicate_checksum_detected(self, initialized_db):
        """get_photo_by_checksum finds existing photo with same hash."""
        checksum = "abc123def456"
        initialized_db.insert_photo(
            filename="original.jpg", filepath="/media/original.jpg",
            checksum_sha256=checksum,
        )

        existing = initialized_db.get_photo_by_checksum(checksum)
        assert existing is not None
        assert existing["filename"] == "original.jpg"

    def test_no_false_duplicate(self, initialized_db):
        """get_photo_by_checksum returns None for different hash."""
        initialized_db.insert_photo(
            filename="unique.jpg", filepath="/media/unique.jpg",
            checksum_sha256="aaa",
        )
        result = initialized_db.get_photo_by_checksum("bbb")
        assert result is None


# ---------------------------------------------------------------------------
# Album CRUD tests
# ---------------------------------------------------------------------------


class TestAlbumCrud:
    """Tests for album create, add photo, remove photo, delete."""

    def test_create_and_list(self, initialized_db):
        """Create an album and list it."""
        aid = initialized_db.create_album("Vacation", "Summer 2025")
        assert aid is not None

        albums = initialized_db.get_albums()
        names = [a["name"] for a in albums]
        assert "Vacation" in names

    def test_add_and_remove_photo(self, initialized_db):
        """Add a photo to an album, then remove it."""
        aid = initialized_db.create_album("Test Album")
        pid = initialized_db.insert_photo(
            filename="album_photo.jpg", filepath="/media/album_photo.jpg"
        )

        initialized_db.add_to_album(pid, aid)
        photos = initialized_db.get_album_photos(aid)
        assert len(photos) == 1
        assert photos[0]["filename"] == "album_photo.jpg"

        initialized_db.remove_from_album(pid, aid)
        photos = initialized_db.get_album_photos(aid)
        assert len(photos) == 0

    def test_add_duplicate_ignored(self, initialized_db):
        """Adding the same photo to an album twice doesn't error."""
        aid = initialized_db.create_album("Dupes")
        pid = initialized_db.insert_photo(
            filename="dup_album.jpg", filepath="/media/dup_album.jpg"
        )
        initialized_db.add_to_album(pid, aid)
        initialized_db.add_to_album(pid, aid)  # Should not raise

        photos = initialized_db.get_album_photos(aid)
        assert len(photos) == 1

    def test_delete_album(self, initialized_db):
        """Deleting an album removes it and its photo associations."""
        aid = initialized_db.create_album("ToDelete")
        pid = initialized_db.insert_photo(
            filename="linked.jpg", filepath="/media/linked.jpg"
        )
        initialized_db.add_to_album(pid, aid)

        initialized_db.delete_album(aid)
        albums = initialized_db.get_albums()
        assert all(a["name"] != "ToDelete" for a in albums)

        # album_photos should be cascade-deleted
        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS c FROM album_photos WHERE album_id = ?",
                (aid,),
            ).fetchone()
            assert rows["c"] == 0

    def test_get_photos_album_filter(self, initialized_db):
        """get_photos with album_id returns only photos in that album."""
        aid = initialized_db.create_album("Filter")
        p1 = initialized_db.insert_photo(
            filename="in_album.jpg", filepath="/media/in_album.jpg"
        )
        initialized_db.insert_photo(
            filename="not_in.jpg", filepath="/media/not_in.jpg"
        )
        initialized_db.add_to_album(p1, aid)

        photos = initialized_db.get_photos(album_id=aid)
        assert len(photos) == 1
        assert photos[0]["filename"] == "in_album.jpg"


# ---------------------------------------------------------------------------
# Tag CRUD tests
# ---------------------------------------------------------------------------


class TestTagCrud:
    """Tests for tag add, remove, list."""

    def test_add_and_list_tags(self, initialized_db):
        """Add tags to a photo and list them."""
        pid = initialized_db.insert_photo(
            filename="tagged.jpg", filepath="/media/tagged.jpg"
        )
        initialized_db.add_tag(pid, "sunset")
        initialized_db.add_tag(pid, "beach")

        tags = initialized_db.get_tags(pid)
        tag_names = [t["name"] for t in tags]
        assert "sunset" in tag_names
        assert "beach" in tag_names

    def test_remove_tag(self, initialized_db):
        """Remove a tag from a photo."""
        pid = initialized_db.insert_photo(
            filename="untagged.jpg", filepath="/media/untagged.jpg"
        )
        tag_id = initialized_db.add_tag(pid, "temporary")
        initialized_db.remove_tag(pid, tag_id)

        tags = initialized_db.get_tags(pid)
        assert len(tags) == 0

    def test_case_insensitive_tags(self, initialized_db):
        """Tags are case-insensitive (COLLATE NOCASE)."""
        pid = initialized_db.insert_photo(
            filename="case.jpg", filepath="/media/case.jpg"
        )
        id1 = initialized_db.add_tag(pid, "Nature")
        id2 = initialized_db.add_tag(pid, "nature")

        # Same tag (case insensitive), should only be one
        tags = initialized_db.get_tags(pid)
        assert len(tags) == 1

    def test_shared_tags(self, initialized_db):
        """Same tag can be applied to multiple photos."""
        p1 = initialized_db.insert_photo(
            filename="share1.jpg", filepath="/media/share1.jpg"
        )
        p2 = initialized_db.insert_photo(
            filename="share2.jpg", filepath="/media/share2.jpg"
        )
        initialized_db.add_tag(p1, "family")
        initialized_db.add_tag(p2, "family")

        tags1 = initialized_db.get_tags(p1)
        tags2 = initialized_db.get_tags(p2)
        assert len(tags1) == 1
        assert len(tags2) == 1
        assert tags1[0]["name"] == tags2[0]["name"]


# ---------------------------------------------------------------------------
# User CRUD tests
# ---------------------------------------------------------------------------


class TestUserCrud:
    """Tests for user create and list."""

    def test_create_and_list(self, initialized_db):
        """Create users and list them."""
        initialized_db.create_user("alice")
        initialized_db.create_user("bob", is_admin=True)

        users = initialized_db.get_users()
        names = [u["name"] for u in users]
        assert "alice" in names
        assert "bob" in names

    def test_get_or_create(self, initialized_db):
        """get_or_create_user returns existing user or creates new one."""
        uid1 = initialized_db.get_or_create_user("charlie")
        uid2 = initialized_db.get_or_create_user("charlie")
        assert uid1 == uid2


# ---------------------------------------------------------------------------
# Stats buffering tests
# ---------------------------------------------------------------------------


class TestStatsBuffering:
    """Tests for record_view and flush."""

    def test_buffer_accumulates(self, initialized_db):
        """record_view adds entries to the buffer."""
        pid = initialized_db.insert_photo(
            filename="stats.jpg", filepath="/media/stats.jpg"
        )
        initialized_db.record_view(pid, 5.0, "fade")
        initialized_db.record_view(pid, 3.0, "slide")

        with initialized_db._stats_buffer_lock:
            assert len(initialized_db._stats_buffer) == 2

    def test_flush_writes_to_db(self, initialized_db):
        """_flush_stats writes buffered entries to display_stats."""
        pid = initialized_db.insert_photo(
            filename="flush.jpg", filepath="/media/flush.jpg"
        )
        initialized_db.record_view(pid, 5.0, "fade")
        initialized_db.record_view(pid, 3.0, "slide")
        initialized_db._flush_stats()

        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS c FROM display_stats WHERE photo_id = ?",
                (pid,),
            ).fetchone()
            assert rows["c"] == 2

        # view_count should be updated on the photo
        photo = initialized_db.get_photo_by_id(pid)
        assert photo["view_count"] == 2

    def test_flush_on_threshold(self, initialized_db):
        """Buffer auto-flushes when threshold is reached."""
        pid = initialized_db.insert_photo(
            filename="thresh.jpg", filepath="/media/thresh.jpg"
        )
        # Fill to threshold
        for i in range(initialized_db._STATS_FLUSH_THRESHOLD):
            initialized_db.record_view(pid, 1.0, "fade")

        # After threshold, buffer should have been flushed
        with initialized_db._stats_buffer_lock:
            assert len(initialized_db._stats_buffer) == 0

        with closing(initialized_db.get_db()) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS c FROM display_stats WHERE photo_id = ?",
                (pid,),
            ).fetchone()
            assert rows["c"] == initialized_db._STATS_FLUSH_THRESHOLD

    def test_empty_flush_is_noop(self, initialized_db):
        """Flushing an empty buffer does nothing and doesn't error."""
        initialized_db._flush_stats()  # Should not raise


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestMigration:
    """Tests for migrate_from_files."""

    def test_migration_creates_photos_from_files(self, initialized_db, tmp_path):
        """Migration scans MEDIA_DIR and creates photo records."""
        media_dir = tmp_path / "media"
        # Create some fake media files
        (media_dir / "photo1.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        (media_dir / "photo2.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        (media_dir / "video1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)

        # Run migration
        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)

        # Check photos were created
        photos = initialized_db.get_photos()
        names = [p["filename"] for p in photos]
        assert "photo1.jpg" in names
        assert "photo2.png" in names
        assert "video1.mp4" in names

    def test_migration_skips_thumbnails_dir(self, initialized_db, tmp_path):
        """Migration skips files in the thumbnails subdirectory."""
        media_dir = tmp_path / "media"
        thumb_dir = media_dir / "thumbnails"
        thumb_dir.mkdir()
        (thumb_dir / "thumb.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)
        (media_dir / "real.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)

        photos = initialized_db.get_photos()
        names = [p["filename"] for p in photos]
        assert "real.jpg" in names
        assert "thumb.jpg" not in names

    def test_migration_imports_gps_cache(self, initialized_db, tmp_path):
        """Migration reads GPS data from the .locations.json cache."""
        import json
        media_dir = tmp_path / "media"
        (media_dir / "gps.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        cache = {"gps.jpg": {"lat": 40.7128, "lon": -74.0060}}
        (media_dir / ".locations.json").write_text(json.dumps(cache))

        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)

        photo = initialized_db.get_photo_by_filename("gps.jpg")
        assert photo is not None
        assert abs(photo["gps_lat"] - 40.7128) < 0.001
        assert abs(photo["gps_lon"] - (-74.0060)) < 0.001

    def test_migration_creates_default_user(self, initialized_db, tmp_path):
        """Migration creates the 'default' user."""
        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)

        users = initialized_db.get_users()
        names = [u["name"] for u in users]
        assert "default" in names

    def test_migration_is_idempotent(self, initialized_db, tmp_path):
        """Running migration twice doesn't duplicate photos."""
        media_dir = tmp_path / "media"
        (media_dir / "idem.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)

        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)
            initialized_db.migrate_from_files(conn)

        photos = initialized_db.get_photos()
        idem_count = sum(1 for p in photos if p["filename"] == "idem.jpg")
        assert idem_count == 1

    def test_migration_deletes_gps_cache(self, initialized_db, tmp_path):
        """Migration deletes .locations.json after importing."""
        import json
        media_dir = tmp_path / "media"
        (media_dir / "del_cache.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 50)
        cache_path = media_dir / ".locations.json"
        cache_path.write_text(json.dumps({"del_cache.jpg": {"lat": 1.0, "lon": 2.0}}))

        with closing(initialized_db.get_db()) as conn:
            initialized_db.migrate_from_files(conn)

        assert not cache_path.exists()


# ---------------------------------------------------------------------------
# Smart album tests
# ---------------------------------------------------------------------------


class TestSmartAlbums:
    """Tests for smart album computed queries."""

    def test_recent_smart_album(self, initialized_db):
        """RECENT smart album returns photos uploaded within 30 days."""
        # Photos inserted with default uploaded_at = now(), which is within 30 days
        initialized_db.insert_photo(
            filename="recent.jpg", filepath="/media/recent.jpg"
        )
        photos = initialized_db.get_smart_album_photos("recent")
        assert len(photos) >= 1
        names = [p["filename"] for p in photos]
        assert "recent.jpg" in names

    def test_most_shown_smart_album(self, initialized_db):
        """MOST SHOWN smart album returns top photos by view_count."""
        pid = initialized_db.insert_photo(
            filename="popular.jpg", filepath="/media/popular.jpg"
        )
        # Manually set view_count
        with initialized_db._write_lock:
            with closing(initialized_db.get_db()) as conn:
                conn.execute(
                    "UPDATE photos SET view_count = 100 WHERE id = ?", (pid,)
                )
                conn.commit()

        photos = initialized_db.get_smart_album_photos("most_shown")
        assert len(photos) >= 1
        assert photos[0]["filename"] == "popular.jpg"

    def test_unknown_smart_album(self, initialized_db):
        """Unknown smart album key returns empty list."""
        photos = initialized_db.get_smart_album_photos("nonexistent")
        assert photos == []


# ---------------------------------------------------------------------------
# Backup tests
# ---------------------------------------------------------------------------


class TestBackup:
    """Tests for database backup."""

    def test_backup_creates_file(self, initialized_db, tmp_path):
        """backup_db creates a backup file."""
        backup_path = initialized_db.backup_db()
        assert Path(backup_path).exists()
        assert Path(backup_path).stat().st_size > 0

    def test_backup_is_valid_sqlite(self, initialized_db, tmp_path):
        """Backup file is a valid SQLite database."""
        backup_path = initialized_db.backup_db()
        with closing(sqlite3.connect(backup_path)) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            assert len(tables) > 0


# ---------------------------------------------------------------------------
# Stats aggregation tests
# ---------------------------------------------------------------------------


class TestGetStats:
    """Tests for the get_stats aggregation."""

    def test_stats_counts(self, initialized_db):
        """get_stats returns correct counts."""
        initialized_db.insert_photo(
            filename="s1.jpg", filepath="/media/s1.jpg"
        )
        initialized_db.insert_photo(
            filename="s2.mp4", filepath="/media/s2.mp4", is_video=True
        )
        p3 = initialized_db.insert_photo(
            filename="s3.jpg", filepath="/media/s3.jpg"
        )
        initialized_db.toggle_favorite(p3)

        stats = initialized_db.get_stats()
        assert stats["total_photos"] == 3
        assert stats["videos"] == 1
        assert stats["favorites"] == 1

    def test_stats_by_user(self, initialized_db):
        """get_stats includes per-user breakdown."""
        initialized_db.get_or_create_user("test_user")
        initialized_db.insert_photo(
            filename="u1.jpg", filepath="/media/u1.jpg",
            uploaded_by="test_user",
        )
        stats = initialized_db.get_stats()
        user_names = [u["uploaded_by"] for u in stats["by_user"]]
        assert "test_user" in user_names
