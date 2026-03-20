"""Tests for map overlay settings in the API."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def test_map_overlay_position_in_settings():
    """MAP_OVERLAY_POSITION appears in _current_settings() with default 'off'."""
    from api import _current_settings
    settings = _current_settings()
    assert "map_overlay_position" in settings
    assert settings["map_overlay_position"] == "off"


def test_valid_map_overlay_positions():
    """Validation constant has the correct values."""
    from api import _VALID_MAP_OVERLAY_POSITIONS
    assert _VALID_MAP_OVERLAY_POSITIONS == {
        "off", "top-left", "top-right", "bottom-left", "bottom-right",
    }


def test_map_overlay_settings_in_env_map():
    """All 9 map overlay settings are wired in _SETTINGS_ENV_MAP."""
    from api import _SETTINGS_ENV_MAP
    expected_keys = [
        "map_overlay_position",
        "map_overlay_opacity",
        "map_overlay_size",
        "map_overlay_zoom",
        "map_overlay_offset",
        "map_overlay_radius",
        "map_overlay_dot_size",
        "map_overlay_dot_pulse",
        "map_overlay_border",
    ]
    for key in expected_keys:
        assert key in _SETTINGS_ENV_MAP, f"{key} missing from _SETTINGS_ENV_MAP"


def test_map_overlay_numeric_defaults():
    """Numeric map overlay settings have correct defaults."""
    from api import _current_settings
    settings = _current_settings()
    assert settings["map_overlay_opacity"] == 0.75
    assert settings["map_overlay_size"] == 180
    assert settings["map_overlay_zoom"] == 11
    assert settings["map_overlay_offset"] == 24
    assert settings["map_overlay_radius"] == 6
    assert settings["map_overlay_dot_size"] == 8


def test_map_overlay_boolean_defaults():
    """Boolean map overlay settings default to True."""
    from api import _current_settings
    settings = _current_settings()
    assert settings["map_overlay_dot_pulse"] is True
    assert settings["map_overlay_border"] is True


def test_map_overlay_env_map_converters():
    """Boolean converters produce yes/no strings."""
    from api import _SETTINGS_ENV_MAP
    _, pulse_conv = _SETTINGS_ENV_MAP["map_overlay_dot_pulse"]
    assert pulse_conv(True) == "yes"
    assert pulse_conv(False) == "no"

    _, border_conv = _SETTINGS_ENV_MAP["map_overlay_border"]
    assert border_conv(True) == "yes"
    assert border_conv(False) == "no"
