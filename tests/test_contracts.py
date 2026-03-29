"""SSE event contract tests.

Validates that SSE event payloads match their JSON Schema definitions
in schemas/sse-events/. Catches payload drift between Python emitters
and frontend consumers.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
SCHEMA_DIR = Path(__file__).parent.parent / "schemas" / "sse-events"

# Every SSE event type emitted in the codebase
ALL_EVENTS = [
    "state:current",
    "heartbeat",
    "sync",
    "error",
    "settings:changed",
    "photo:favorited",
    "photo:deleted",
    "slideshow:now_playing",
    "slideshow:show",
    "update:rebooting",
    "photo:added",
]


def load_schema(event_name):
    """Load the JSON Schema for a given SSE event type."""
    filename = event_name.replace(":", "-") + ".json"
    schema_path = SCHEMA_DIR / filename
    assert schema_path.exists(), f"No schema for '{event_name}'"
    return json.loads(schema_path.read_text())


# --- Coverage: every known event has a schema file ---


class TestSchemaCoverage:
    """Verify that every known SSE event has a corresponding schema."""

    def test_all_events_have_schemas(self):
        for event in ALL_EVENTS:
            filename = event.replace(":", "-") + ".json"
            schema_path = SCHEMA_DIR / filename
            assert schema_path.exists(), f"Missing schema file for event '{event}': {filename}"

    def test_no_orphan_schemas(self):
        """Every schema file should correspond to a known event."""
        expected_files = {e.replace(":", "-") + ".json" for e in ALL_EVENTS}
        actual_files = {f.name for f in SCHEMA_DIR.glob("*.json")}
        orphans = actual_files - expected_files
        assert not orphans, f"Orphan schema files (no matching event): {orphans}"

    def test_schemas_are_valid_json(self):
        """Every schema file must be parseable JSON."""
        for schema_file in SCHEMA_DIR.glob("*.json"):
            try:
                json.loads(schema_file.read_text())
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON in {schema_file.name}: {exc}")


# --- state:current ---


class TestStateCurrentContract:
    def test_valid_full(self):
        schema = load_schema("state:current")
        validate({"connected": True, "clients": 3}, schema)

    def test_valid_without_clients(self):
        """clients is optional (omitted when state retrieval fails)."""
        schema = load_schema("state:current")
        validate({"connected": True}, schema)

    def test_invalid_connected_false(self):
        """connected is always True in the source."""
        schema = load_schema("state:current")
        with pytest.raises(ValidationError):
            validate({"connected": False}, schema)

    def test_invalid_missing_connected(self):
        schema = load_schema("state:current")
        with pytest.raises(ValidationError):
            validate({"clients": 2}, schema)

    def test_invalid_extra_field(self):
        schema = load_schema("state:current")
        with pytest.raises(ValidationError):
            validate({"connected": True, "clients": 1, "extra": "nope"}, schema)


# --- heartbeat ---


class TestHeartbeatContract:
    def test_valid(self):
        schema = load_schema("heartbeat")
        validate({"ts": int(time.time())}, schema)

    def test_invalid_missing_ts(self):
        schema = load_schema("heartbeat")
        with pytest.raises(ValidationError):
            validate({}, schema)

    def test_invalid_ts_string(self):
        schema = load_schema("heartbeat")
        with pytest.raises(ValidationError):
            validate({"ts": "1234567890"}, schema)


# --- sync ---


class TestSyncContract:
    def test_valid(self):
        schema = load_schema("sync")
        validate({"reason": "client_overflow"}, schema)

    def test_invalid_unknown_reason(self):
        schema = load_schema("sync")
        with pytest.raises(ValidationError):
            validate({"reason": "unknown"}, schema)

    def test_invalid_missing_reason(self):
        schema = load_schema("sync")
        with pytest.raises(ValidationError):
            validate({}, schema)


# --- error ---


class TestErrorContract:
    def test_valid(self):
        schema = load_schema("error")
        validate({"error": "Too many connections"}, schema)

    def test_invalid_missing_error(self):
        schema = load_schema("error")
        with pytest.raises(ValidationError):
            validate({}, schema)

    def test_invalid_error_not_string(self):
        schema = load_schema("error")
        with pytest.raises(ValidationError):
            validate({"error": 42}, schema)


# --- settings:changed ---


class TestSettingsChangedContract:
    @pytest.fixture()
    def valid_settings(self):
        return {
            "photo_duration": 10,
            "shuffle": True,
            "transition_type": "fade",
            "transition_mode": "single",
            "transition_duration_ms": 1000,
            "kenburns_intensity": "moderate",
            "photo_order": "shuffle",
            "qr_display_seconds": 30,
            "hdmi_schedule_enabled": False,
            "hdmi_off_time": "22:00",
            "hdmi_on_time": "08:00",
            "schedule_days": "0,1,2,3,4,5,6",
            "max_upload_mb": 200,
            "auto_resize_max": 1920,
            "auto_update_enabled": False,
            "pin_length": 4,
            "max_video_duration": 30,
            "web_port": 8080,
        }

    def test_valid_full(self, valid_settings):
        schema = load_schema("settings:changed")
        validate(valid_settings, schema)

    def test_valid_pin_length_6(self, valid_settings):
        schema = load_schema("settings:changed")
        valid_settings["pin_length"] = 6
        validate(valid_settings, schema)

    def test_invalid_missing_field(self, valid_settings):
        schema = load_schema("settings:changed")
        del valid_settings["photo_duration"]
        with pytest.raises(ValidationError):
            validate(valid_settings, schema)

    def test_invalid_pin_length_5(self, valid_settings):
        schema = load_schema("settings:changed")
        valid_settings["pin_length"] = 5
        with pytest.raises(ValidationError):
            validate(valid_settings, schema)

    def test_invalid_time_format(self, valid_settings):
        schema = load_schema("settings:changed")
        valid_settings["hdmi_off_time"] = "10pm"
        with pytest.raises(ValidationError):
            validate(valid_settings, schema)

    def test_invalid_extra_field(self, valid_settings):
        schema = load_schema("settings:changed")
        valid_settings["unknown_setting"] = "value"
        with pytest.raises(ValidationError):
            validate(valid_settings, schema)


# --- photo:favorited ---


class TestPhotoFavoritedContract:
    def test_valid_favorited(self):
        schema = load_schema("photo:favorited")
        validate({"id": 42, "is_favorite": True}, schema)

    def test_valid_unfavorited(self):
        schema = load_schema("photo:favorited")
        validate({"id": 1, "is_favorite": False}, schema)

    def test_invalid_missing_id(self):
        schema = load_schema("photo:favorited")
        with pytest.raises(ValidationError):
            validate({"is_favorite": True}, schema)

    def test_invalid_id_string(self):
        schema = load_schema("photo:favorited")
        with pytest.raises(ValidationError):
            validate({"id": "42", "is_favorite": True}, schema)


# --- photo:deleted ---


class TestPhotoDeletedContract:
    def test_valid_batch_delete(self):
        """api.py batch delete sends {count: int}."""
        schema = load_schema("photo:deleted")
        validate({"count": 5}, schema)

    def test_valid_single_delete(self):
        """web_upload.py single delete sends {filename: str}."""
        schema = load_schema("photo:deleted")
        validate({"filename": "photo.jpg"}, schema)

    def test_invalid_both_fields(self):
        """Cannot have both count and filename."""
        schema = load_schema("photo:deleted")
        with pytest.raises(ValidationError):
            validate({"count": 1, "filename": "photo.jpg"}, schema)

    def test_invalid_empty(self):
        schema = load_schema("photo:deleted")
        with pytest.raises(ValidationError):
            validate({}, schema)

    def test_invalid_count_string(self):
        schema = load_schema("photo:deleted")
        with pytest.raises(ValidationError):
            validate({"count": "5"}, schema)


# --- slideshow:now_playing ---


class TestSlideshowNowPlayingContract:
    def test_valid_with_values(self):
        schema = load_schema("slideshow:now_playing")
        validate({"photo_id": 42, "filename": "sunset.jpg"}, schema)

    def test_valid_with_nulls(self):
        """Fields may be null if data.get() returns None from request JSON."""
        schema = load_schema("slideshow:now_playing")
        validate({"photo_id": None, "filename": None}, schema)

    def test_invalid_missing_photo_id(self):
        schema = load_schema("slideshow:now_playing")
        with pytest.raises(ValidationError):
            validate({"filename": "sunset.jpg"}, schema)

    def test_invalid_missing_filename(self):
        schema = load_schema("slideshow:now_playing")
        with pytest.raises(ValidationError):
            validate({"photo_id": 42}, schema)


# --- slideshow:show ---


class TestSlideshowShowContract:
    def test_valid(self):
        schema = load_schema("slideshow:show")
        validate(
            {
                "photo_id": 7,
                "filename": "beach.jpg",
                "filepath": "/home/pi/photos/beach.jpg",
                "is_video": False,
            },
            schema,
        )

    def test_valid_video(self):
        schema = load_schema("slideshow:show")
        validate(
            {
                "photo_id": 12,
                "filename": "clip.mp4",
                "filepath": "/home/pi/photos/clip.mp4",
                "is_video": True,
            },
            schema,
        )

    def test_invalid_missing_filepath(self):
        schema = load_schema("slideshow:show")
        with pytest.raises(ValidationError):
            validate(
                {"photo_id": 7, "filename": "beach.jpg", "is_video": False},
                schema,
            )

    def test_invalid_is_video_string(self):
        schema = load_schema("slideshow:show")
        with pytest.raises(ValidationError):
            validate(
                {
                    "photo_id": 7,
                    "filename": "beach.jpg",
                    "filepath": "/home/pi/photos/beach.jpg",
                    "is_video": "no",
                },
                schema,
            )


# --- update:rebooting ---


class TestUpdateRebootingContract:
    def test_valid(self):
        schema = load_schema("update:rebooting")
        validate({"version": "v2.2.1"}, schema)

    def test_invalid_missing_version(self):
        schema = load_schema("update:rebooting")
        with pytest.raises(ValidationError):
            validate({}, schema)

    def test_invalid_empty_version(self):
        schema = load_schema("update:rebooting")
        with pytest.raises(ValidationError):
            validate({"version": ""}, schema)

    def test_invalid_version_not_string(self):
        schema = load_schema("update:rebooting")
        with pytest.raises(ValidationError):
            validate({"version": 210}, schema)


# --- photo:added ---


class TestPhotoAddedContract:
    def test_valid(self):
        schema = load_schema("photo:added")
        validate({"filename": "vacation.jpg", "photo_id": 99}, schema)

    def test_invalid_missing_filename(self):
        schema = load_schema("photo:added")
        with pytest.raises(ValidationError):
            validate({"photo_id": 99}, schema)

    def test_invalid_missing_photo_id(self):
        schema = load_schema("photo:added")
        with pytest.raises(ValidationError):
            validate({"filename": "vacation.jpg"}, schema)

    def test_invalid_photo_id_string(self):
        schema = load_schema("photo:added")
        with pytest.raises(ValidationError):
            validate({"filename": "vacation.jpg", "photo_id": "99"}, schema)
