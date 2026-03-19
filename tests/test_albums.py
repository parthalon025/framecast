"""Tests for favorites, albums, tags, and smart album API endpoints.

Covers: favorite toggle, album CRUD, smart album queries, tag CRUD,
photo filter parameter, and get_all_tags autocomplete.
"""

from contextlib import closing
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Favorite toggle tests
# ---------------------------------------------------------------------------


class TestFavoriteToggleAPI:
    """Tests for the POST /api/photos/<id>/favorite endpoint logic."""

    def test_toggle_favorite_on(self, initialized_db):
        """Toggling favorite on returns is_favorite=True."""
        pid = initialized_db.insert_photo(
            filename="fav_on.jpg", filepath="/media/fav_on.jpg"
        )
        result = initialized_db.toggle_favorite(pid)
        assert result is True

        photo = initialized_db.get_photo_by_id(pid)
        assert photo["is_favorite"] == 1

    def test_toggle_favorite_off(self, initialized_db):
        """Toggling favorite twice returns is_favorite=False."""
        pid = initialized_db.insert_photo(
            filename="fav_off.jpg", filepath="/media/fav_off.jpg"
        )
        initialized_db.toggle_favorite(pid)  # on
        result = initialized_db.toggle_favorite(pid)  # off
        assert result is False

    def test_toggle_favorite_nonexistent(self, initialized_db):
        """Toggling favorite on non-existent photo returns None."""
        result = initialized_db.toggle_favorite(99999)
        assert result is None

    def test_favorite_filter(self, initialized_db):
        """get_photos with favorite_only returns only favorited photos."""
        p1 = initialized_db.insert_photo(
            filename="fav_filter1.jpg", filepath="/media/fav_filter1.jpg"
        )
        initialized_db.insert_photo(
            filename="fav_filter2.jpg", filepath="/media/fav_filter2.jpg"
        )
        initialized_db.toggle_favorite(p1)

        favs = initialized_db.get_photos(favorite_only=True)
        assert len(favs) == 1
        assert favs[0]["filename"] == "fav_filter1.jpg"

    def test_hidden_filter(self, initialized_db):
        """get_photos with include_hidden returns hidden photos."""
        pid = initialized_db.insert_photo(
            filename="hidden.jpg", filepath="/media/hidden.jpg"
        )
        initialized_db.toggle_hidden(pid)

        # Default excludes hidden
        default = initialized_db.get_photos()
        assert all(p["filename"] != "hidden.jpg" for p in default)

        # With include_hidden
        hidden = initialized_db.get_photos(include_hidden=True)
        names = [p["filename"] for p in hidden]
        assert "hidden.jpg" in names


# ---------------------------------------------------------------------------
# Album CRUD API tests
# ---------------------------------------------------------------------------


class TestAlbumCrudAPI:
    """Tests for album creation, listing, photo management, and deletion."""

    def test_create_album(self, initialized_db):
        """Creating an album returns a valid id."""
        aid = initialized_db.create_album("Test Album", "A test description")
        assert aid is not None
        assert aid > 0

    def test_create_duplicate_album_raises(self, initialized_db):
        """Creating an album with a duplicate name raises an error."""
        initialized_db.create_album("Unique")
        with pytest.raises(Exception, match="UNIQUE"):
            initialized_db.create_album("Unique")

    def test_list_albums_includes_photo_count(self, initialized_db):
        """get_albums returns photo_count for each album."""
        aid = initialized_db.create_album("Counted")
        p1 = initialized_db.insert_photo(
            filename="count1.jpg", filepath="/media/count1.jpg"
        )
        p2 = initialized_db.insert_photo(
            filename="count2.jpg", filepath="/media/count2.jpg"
        )
        initialized_db.add_to_album(p1, aid)
        initialized_db.add_to_album(p2, aid)

        albums = initialized_db.get_albums()
        counted = [a for a in albums if a["name"] == "Counted"][0]
        assert counted["photo_count"] == 2

    def test_album_photos_listing(self, initialized_db):
        """get_album_photos returns all photos in an album."""
        aid = initialized_db.create_album("Listed")
        pid = initialized_db.insert_photo(
            filename="listed.jpg", filepath="/media/listed.jpg"
        )
        initialized_db.add_to_album(pid, aid)

        photos = initialized_db.get_album_photos(aid)
        assert len(photos) == 1
        assert photos[0]["filename"] == "listed.jpg"

    def test_remove_photo_from_album(self, initialized_db):
        """Removing a photo from an album reduces the count."""
        aid = initialized_db.create_album("Remove")
        pid = initialized_db.insert_photo(
            filename="removable.jpg", filepath="/media/removable.jpg"
        )
        initialized_db.add_to_album(pid, aid)
        initialized_db.remove_from_album(pid, aid)

        photos = initialized_db.get_album_photos(aid)
        assert len(photos) == 0

    def test_delete_album_preserves_photos(self, initialized_db):
        """Deleting an album does not delete the photos themselves."""
        aid = initialized_db.create_album("Deleteable")
        pid = initialized_db.insert_photo(
            filename="preserved.jpg", filepath="/media/preserved.jpg"
        )
        initialized_db.add_to_album(pid, aid)
        initialized_db.delete_album(aid)

        # Photo still exists
        photo = initialized_db.get_photo_by_id(pid)
        assert photo is not None
        assert photo["quarantined"] == 0

    def test_delete_album_cascades_album_photos(self, initialized_db):
        """Deleting an album removes entries from album_photos."""
        aid = initialized_db.create_album("CascadeTest")
        pid = initialized_db.insert_photo(
            filename="cascade.jpg", filepath="/media/cascade.jpg"
        )
        initialized_db.add_to_album(pid, aid)
        initialized_db.delete_album(aid)

        with closing(initialized_db.get_db()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM album_photos WHERE album_id = ?",
                (aid,),
            ).fetchone()["c"]
        assert count == 0


# ---------------------------------------------------------------------------
# Smart album tests
# ---------------------------------------------------------------------------


class TestSmartAlbumsAPI:
    """Tests for smart album computed queries."""

    def test_recent_returns_new_photos(self, initialized_db):
        """RECENT smart album includes recently uploaded photos."""
        initialized_db.insert_photo(
            filename="smart_recent.jpg", filepath="/media/smart_recent.jpg"
        )
        photos = initialized_db.get_smart_album_photos("recent")
        names = [p["filename"] for p in photos]
        assert "smart_recent.jpg" in names

    def test_most_shown_ordered_by_views(self, initialized_db):
        """MOST SHOWN smart album orders by view_count descending."""
        p1 = initialized_db.insert_photo(
            filename="views_high.jpg", filepath="/media/views_high.jpg"
        )
        p2 = initialized_db.insert_photo(
            filename="views_low.jpg", filepath="/media/views_low.jpg"
        )
        # Set view counts directly
        with initialized_db._write_lock:
            with closing(initialized_db.get_db()) as conn:
                conn.execute("UPDATE photos SET view_count = 50 WHERE id = ?", (p1,))
                conn.execute("UPDATE photos SET view_count = 5 WHERE id = ?", (p2,))
                conn.commit()

        photos = initialized_db.get_smart_album_photos("most_shown")
        assert len(photos) >= 2
        assert photos[0]["filename"] == "views_high.jpg"
        assert photos[1]["filename"] == "views_low.jpg"

    def test_unknown_smart_album_empty(self, initialized_db):
        """Unknown smart album key returns empty list."""
        photos = initialized_db.get_smart_album_photos("nonexistent_key")
        assert photos == []

    def test_smart_albums_exclude_quarantined(self, initialized_db):
        """Smart albums do not include quarantined photos."""
        initialized_db.insert_photo(
            filename="quarantined.jpg", filepath="/media/quarantined.jpg",
            quarantined=True, quarantine_reason="test",
        )
        for key in ("recent", "most_shown"):
            photos = initialized_db.get_smart_album_photos(key)
            names = [p["filename"] for p in photos]
            assert "quarantined.jpg" not in names


# ---------------------------------------------------------------------------
# Tag CRUD API tests
# ---------------------------------------------------------------------------


class TestTagCrudAPI:
    """Tests for tag add, remove, list, and autocomplete."""

    def test_add_tag(self, initialized_db):
        """Adding a tag returns a valid tag id."""
        pid = initialized_db.insert_photo(
            filename="tag_add.jpg", filepath="/media/tag_add.jpg"
        )
        tag_id = initialized_db.add_tag(pid, "landscape")
        assert tag_id is not None
        assert tag_id > 0

    def test_list_photo_tags(self, initialized_db):
        """get_tags returns tags for a specific photo."""
        pid = initialized_db.insert_photo(
            filename="tag_list.jpg", filepath="/media/tag_list.jpg"
        )
        initialized_db.add_tag(pid, "sunset")
        initialized_db.add_tag(pid, "ocean")

        tags = initialized_db.get_tags(pid)
        names = [t["name"] for t in tags]
        assert "sunset" in names
        assert "ocean" in names

    def test_remove_tag(self, initialized_db):
        """Removing a tag disassociates it from the photo."""
        pid = initialized_db.insert_photo(
            filename="tag_rm.jpg", filepath="/media/tag_rm.jpg"
        )
        tag_id = initialized_db.add_tag(pid, "temporary")
        initialized_db.remove_tag(pid, tag_id)

        tags = initialized_db.get_tags(pid)
        assert len(tags) == 0

    def test_get_all_tags(self, initialized_db):
        """get_all_tags returns all tags in the system."""
        p1 = initialized_db.insert_photo(
            filename="all_tags1.jpg", filepath="/media/all_tags1.jpg"
        )
        p2 = initialized_db.insert_photo(
            filename="all_tags2.jpg", filepath="/media/all_tags2.jpg"
        )
        initialized_db.add_tag(p1, "family")
        initialized_db.add_tag(p2, "vacation")
        initialized_db.add_tag(p2, "summer")

        all_tags = initialized_db.get_all_tags()
        names = [t["name"] for t in all_tags]
        assert "family" in names
        assert "vacation" in names
        assert "summer" in names

    def test_get_all_tags_empty(self, initialized_db):
        """get_all_tags returns empty list when no tags exist."""
        all_tags = initialized_db.get_all_tags()
        assert all_tags == []

    def test_case_insensitive_dedup(self, initialized_db):
        """Tags with different cases reuse the same tag row."""
        pid = initialized_db.insert_photo(
            filename="case_tag.jpg", filepath="/media/case_tag.jpg"
        )
        id1 = initialized_db.add_tag(pid, "Nature")
        id2 = initialized_db.add_tag(pid, "nature")

        tags = initialized_db.get_tags(pid)
        assert len(tags) == 1

    def test_shared_tag_across_photos(self, initialized_db):
        """Same tag name applied to different photos uses one tag row."""
        p1 = initialized_db.insert_photo(
            filename="shared1.jpg", filepath="/media/shared1.jpg"
        )
        p2 = initialized_db.insert_photo(
            filename="shared2.jpg", filepath="/media/shared2.jpg"
        )
        initialized_db.add_tag(p1, "party")
        initialized_db.add_tag(p2, "party")

        # Only one tag row
        all_tags = initialized_db.get_all_tags()
        party_tags = [t for t in all_tags if t["name"] == "party"]
        assert len(party_tags) == 1
