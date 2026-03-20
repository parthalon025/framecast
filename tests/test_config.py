"""Tests for app/modules/config.py — parsing, atomic writes, env overrides."""

import os
import sys
import threading

import pytest

# app/ is already on sys.path via conftest.py
import modules.config as config

# Capture the real config.get at import time, before any test fixtures
# patch it. conftest.py's autouse fixture replaces modules.config.get
# with _fake_get — we need to restore the original for these tests.
_real_get = config.get


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Point config module at a temporary .env file and reset cache.

    Restores the real config.get since conftest autouse patches it.
    """
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    # Restore the real config.get (conftest autouse patches it with _fake_get)
    monkeypatch.setattr("modules.config.get", _real_get)

    # Clear the module-level cache so each test starts fresh
    with config._lock:
        config._cache.clear()

    yield env_file

    # Clean up cache after test
    with config._lock:
        config._cache.clear()


# ---------------------------------------------------------------------------
# load_env parsing tests
# ---------------------------------------------------------------------------


class TestLoadEnv:
    """Tests for load_env() .env file parsing."""

    def test_load_env_parses_keyvalue(self, _isolate_config):
        """Basic KEY=value lines are parsed correctly."""
        _isolate_config.write_text("HOST=localhost\nPORT=8080\n")
        result = config.load_env()
        assert result["HOST"] == "localhost"
        assert result["PORT"] == "8080"

    def test_load_env_strips_quotes(self, _isolate_config):
        """Quoted values have surrounding quotes removed."""
        _isolate_config.write_text(
            'SINGLE=\'hello world\'\n'
            'DOUBLE="goodbye world"\n'
        )
        result = config.load_env()
        assert result["SINGLE"] == "hello world"
        assert result["DOUBLE"] == "goodbye world"

    def test_load_env_skips_comments(self, _isolate_config):
        """Lines starting with # are skipped."""
        _isolate_config.write_text(
            "# This is a comment\n"
            "KEY=value\n"
            "# Another comment\n"
        )
        result = config.load_env()
        assert len(result) == 1
        assert result["KEY"] == "value"

    def test_load_env_skips_blank_lines(self, _isolate_config):
        """Empty/blank lines are skipped without error."""
        _isolate_config.write_text("\nKEY=value\n\n\n")
        result = config.load_env()
        assert result["KEY"] == "value"
        assert len(result) == 1

    def test_load_env_missing_file(self, _isolate_config):
        """Non-existent .env file returns empty dict (no error)."""
        # Don't create the file
        result = config.load_env()
        assert result == {}

    def test_load_env_value_with_equals(self, _isolate_config):
        """Values containing '=' are parsed correctly (only first '=' splits)."""
        _isolate_config.write_text("URL=http://host:8080?foo=bar\n")
        result = config.load_env()
        assert result["URL"] == "http://host:8080?foo=bar"


# ---------------------------------------------------------------------------
# get() with env override
# ---------------------------------------------------------------------------


class TestGet:
    """Tests for config.get() — os.environ > .env > default."""

    def test_get_from_env_file(self, _isolate_config):
        """get() reads from .env when no env var override exists."""
        _isolate_config.write_text("MY_KEY=from_file\n")
        # Clear cache so it re-reads
        with config._lock:
            config._cache.clear()

        assert config.get("MY_KEY") == "from_file"

    def test_get_env_override(self, _isolate_config, monkeypatch):
        """os.environ overrides .env file value."""
        _isolate_config.write_text("MY_KEY=from_file\n")
        monkeypatch.setenv("MY_KEY", "from_env")

        # Clear cache to force reload
        with config._lock:
            config._cache.clear()

        assert config.get("MY_KEY") == "from_env"

    def test_get_default(self, _isolate_config):
        """get() returns default when key is not in .env or os.environ."""
        assert config.get("MISSING_KEY", "fallback") == "fallback"

    def test_get_default_empty_string(self, _isolate_config):
        """get() returns empty string as default when key is missing and no default given."""
        assert config.get("MISSING_KEY") == ""


# ---------------------------------------------------------------------------
# save() atomic write tests
# ---------------------------------------------------------------------------


class TestSave:
    """Tests for config.save() — atomic writes preserving comments."""

    def test_save_atomic_write(self, _isolate_config):
        """save() creates file and writes values correctly."""
        config.save({"NEW_KEY": "new_value"})

        content = _isolate_config.read_text()
        assert "NEW_KEY=new_value" in content

    def test_save_updates_existing(self, _isolate_config):
        """save() updates an existing key's value."""
        _isolate_config.write_text("EXISTING=old\n")
        config.save({"EXISTING": "new"})

        content = _isolate_config.read_text()
        assert "EXISTING=new" in content
        assert "EXISTING=old" not in content

    def test_save_preserves_comments(self, _isolate_config):
        """Existing comments survive a save operation."""
        _isolate_config.write_text(
            "# Important comment\n"
            "KEY1=value1\n"
            "# Another comment\n"
            "KEY2=value2\n"
        )

        config.save({"KEY1": "updated"})

        content = _isolate_config.read_text()
        assert "# Important comment" in content
        assert "# Another comment" in content
        assert "KEY1=updated" in content
        assert "KEY2=value2" in content

    def test_save_adds_new_key(self, _isolate_config):
        """save() appends new keys that don't exist in the file."""
        _isolate_config.write_text("EXISTING=value\n")
        config.save({"BRAND_NEW": "fresh"})

        content = _isolate_config.read_text()
        assert "EXISTING=value" in content
        assert "BRAND_NEW=fresh" in content

    def test_save_updates_cache(self, _isolate_config):
        """save() updates the in-memory cache so subsequent get() reflects the change."""
        _isolate_config.write_text("CACHED=old\n")
        # Prime cache
        with config._lock:
            config._cache.clear()
        config.get("CACHED")

        config.save({"CACHED": "new"})
        assert config.get("CACHED") == "new"
