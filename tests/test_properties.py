"""Property-based tests using Hypothesis for FrameCast.

Tests invariants that must hold for all inputs: format consistency,
determinism, symmetry, boundedness, and crash-freedom.
"""

import os
import re
import sys

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# app/ is already on sys.path via conftest.py


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 16-char lowercase hex strings (64-bit dhash)
hex_hash = st.text(
    alphabet="0123456789abcdef",
    min_size=16,
    max_size=16,
)


# ---------------------------------------------------------------------------
# media.py — format_size
# ---------------------------------------------------------------------------


class TestFormatSize:
    """Properties of media.format_size."""

    @given(size=st.integers(min_value=0, max_value=2**63))
    def test_output_matches_human_readable_pattern(self, size):
        """format_size always returns '<number> <unit>' in a known set."""
        from modules.media import format_size

        result = format_size(size)
        assert re.match(r"^\d+(\.\d+)? (B|KB|MB|GB|TB)$", result), (
            f"format_size({size}) = {result!r} doesn't match pattern"
        )

    @given(size=st.integers(min_value=0, max_value=2**63))
    def test_deterministic(self, size):
        """Same input always produces the same output."""
        from modules.media import format_size

        assert format_size(size) == format_size(size)


# ---------------------------------------------------------------------------
# media.py — allowed_file
# ---------------------------------------------------------------------------


class TestAllowedFile:
    """Properties of media.allowed_file."""

    @given(filename=st.text())
    def test_never_raises(self, filename):
        """allowed_file never raises, always returns bool."""
        from modules.media import allowed_file

        result = allowed_file(filename)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# media.py — hamming_distance
# ---------------------------------------------------------------------------


class TestHammingDistance:
    """Properties of media.hamming_distance."""

    @given(a=hex_hash, b=hex_hash)
    def test_symmetric(self, a, b):
        """hamming_distance(a, b) == hamming_distance(b, a)."""
        from modules.media import hamming_distance

        assert hamming_distance(a, b) == hamming_distance(b, a)

    @given(a=hex_hash)
    def test_identity(self, a):
        """hamming_distance(a, a) == 0."""
        from modules.media import hamming_distance

        assert hamming_distance(a, a) == 0

    @given(a=hex_hash, b=hex_hash)
    def test_bounded(self, a, b):
        """0 <= hamming_distance(a, b) <= 64."""
        from modules.media import hamming_distance

        d = hamming_distance(a, b)
        assert 0 <= d <= 64

    def test_returns_max_for_none_inputs(self):
        """hamming_distance returns 64 when either input is None."""
        from modules.media import hamming_distance

        assert hamming_distance(None, "0" * 16) == 64
        assert hamming_distance("0" * 16, None) == 64
        assert hamming_distance(None, None) == 64


# ---------------------------------------------------------------------------
# sse.py — _replay_events_after
# ---------------------------------------------------------------------------


class TestReplayEventsAfter:
    """Properties of sse._replay_events_after."""

    @pytest.fixture(autouse=True)
    def _reset_sse_state(self):
        """Clear SSE module state before each test."""
        import sse

        with sse._clients_lock:
            sse._clients.clear()
        with sse._recent_lock:
            sse._recent_events.clear()
        with sse._event_id_lock:
            sse._event_id = 0

    @given(val=st.one_of(st.none(), st.integers(), st.text()))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_never_raises(self, val):
        """_replay_events_after never raises for any input."""
        import sse

        # Consume the generator fully — it should not raise
        list(sse._replay_events_after(val))


# ---------------------------------------------------------------------------
# sse.py — notify
# ---------------------------------------------------------------------------


class TestNotify:
    """Properties of sse.notify."""

    @pytest.fixture(autouse=True)
    def _reset_sse_state(self):
        """Clear SSE module state before each test."""
        import sse

        with sse._clients_lock:
            sse._clients.clear()
        with sse._recent_lock:
            sse._recent_events.clear()
        with sse._event_id_lock:
            sse._event_id = 0

    @given(event=st.text(), data=st.fixed_dictionaries({
        "key": st.text(min_size=0, max_size=20),
    }))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_never_raises(self, event, data):
        """notify never raises for text events with dict data."""
        import sse

        sse.notify(event, data)


# ---------------------------------------------------------------------------
# db.py — search_photos
# ---------------------------------------------------------------------------


class TestSearchPhotos:
    """Properties of db.search_photos."""

    @given(query=st.text(min_size=0, max_size=100))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_never_raises_returns_list(self, query, initialized_db):
        """search_photos never raises and always returns a list."""
        result = initialized_db.search_photos(query)
        assert isinstance(result, list)

    def test_empty_query_returns_empty(self, initialized_db):
        """search_photos('') returns an empty list."""
        assert initialized_db.search_photos("") == []


# ---------------------------------------------------------------------------
# auth.py — generate_pin
# ---------------------------------------------------------------------------


class TestGeneratePin:
    """Properties of auth.generate_pin."""

    @given(st.data())
    @settings(max_examples=200)
    def test_4_digit_pin(self, data):
        """generate_pin(4) → 4-digit string, no leading zero."""
        from modules.auth import generate_pin

        pin = generate_pin(4)
        assert len(pin) == 4, f"Expected 4 digits, got {pin!r}"
        assert pin.isdigit(), f"Expected all digits, got {pin!r}"
        assert pin[0] != "0", f"Leading zero: {pin!r}"

    @given(st.data())
    @settings(max_examples=200)
    def test_6_digit_pin(self, data):
        """generate_pin(6) → 6-digit string, no leading zero."""
        from modules.auth import generate_pin

        pin = generate_pin(6)
        assert len(pin) == 6, f"Expected 6 digits, got {pin!r}"
        assert pin.isdigit(), f"Expected all digits, got {pin!r}"
        assert pin[0] != "0", f"Leading zero: {pin!r}"


# ---------------------------------------------------------------------------
# rotation.py — _compute_weight
# ---------------------------------------------------------------------------


class TestComputeWeight:
    """Properties of rotation._compute_weight."""

    @given(
        is_favorite=st.booleans(),
        in_recent=st.booleans(),
        total=st.integers(min_value=1, max_value=10000),
        recent_ratio=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_always_positive(self, is_favorite, in_recent, total, recent_ratio):
        """_compute_weight always returns a positive float."""
        from modules.rotation import _compute_weight

        photo = {
            "id": 1,
            "is_favorite": is_favorite,
            "uploaded_at": None,
        }
        recent_count = int(total * recent_ratio)
        recent_shown_ids = set(range(recent_count))
        if in_recent:
            recent_shown_ids.add(1)

        weight = _compute_weight(photo, recent_shown_ids, total)
        assert isinstance(weight, float)
        assert weight > 0, f"Weight must be positive, got {weight}"
