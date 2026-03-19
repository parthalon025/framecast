"""Shared test fixtures for FrameCast tests."""

import os
import sys
from unittest import mock

import pytest

# Add the app directory to sys.path so modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Patch config and media before importing db
# so db.py doesn't try to read a real .env or media dir at import time.
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

    # Patch config.get and media.get_media_dir before any db import usage
    monkeypatch.setattr("modules.config.get", _fake_get)
    monkeypatch.setattr("modules.media.get_media_dir", lambda: str(_test_media_dir))

    # Reset db module state between tests
    import modules.db as db_mod
    db_mod._stats_buffer.clear()
    if db_mod._flush_timer is not None:
        db_mod._flush_timer.cancel()
        db_mod._flush_timer = None

    yield tmp_path

    # Clean up timer after test
    if db_mod._flush_timer is not None:
        db_mod._flush_timer.cancel()
        db_mod._flush_timer = None


@pytest.fixture
def db_mod():
    """Return the db module (already patched by isolated_media_dir)."""
    import modules.db as mod
    return mod


@pytest.fixture
def initialized_db(db_mod):
    """Initialize the database and return the module."""
    # Suppress the periodic flush timer in tests
    with mock.patch.object(db_mod, "_start_flush_timer"):
        db_mod.init_db()
    return db_mod
