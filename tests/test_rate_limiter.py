"""Tests for app/modules/rate_limiter.py — window, reset, eviction."""

import time
from unittest import mock

import pytest

import sys
import os

# app/ is already on sys.path via conftest.py
from modules.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Core rate limiting behavior
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_under_limit_allowed(self):
        """Returns None when under max_attempts."""
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        assert limiter.check("client-a") is None  # 1st
        assert limiter.check("client-a") is None  # 2nd
        assert limiter.check("client-a") is None  # 3rd

    def test_over_limit_blocked(self):
        """Returns retry_after > 0 when max_attempts exceeded."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.check("client-b")  # 1st
        limiter.check("client-b")  # 2nd
        result = limiter.check("client-b")  # 3rd — should be blocked
        assert result is not None
        assert result > 0

    def test_window_expiry(self, monkeypatch):
        """Counter resets after window_seconds elapse.

        Uses monkeypatch on time.monotonic to simulate time passing
        without actually sleeping.
        """
        limiter = RateLimiter(max_attempts=2, window_seconds=10)
        base_time = 1000.0

        with mock.patch("modules.rate_limiter.time.monotonic") as mock_mono:
            # Exhaust attempts at t=1000
            mock_mono.return_value = base_time
            limiter.check("client-c")  # 1st
            limiter.check("client-c")  # 2nd

            # 3rd at t=1000 — should be blocked
            result = limiter.check("client-c")
            assert result is not None

            # Advance past window (10s + 1)
            mock_mono.return_value = base_time + 11
            result = limiter.check("client-c")
            assert result is None  # Window expired, counter reset

    def test_reset_clears_counter(self):
        """Explicit reset removes the key's counter entirely."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.check("client-d")  # 1st
        limiter.check("client-d")  # 2nd — at limit

        limiter.reset("client-d")

        # Should be allowed again (counter cleared)
        assert limiter.check("client-d") is None

    def test_stale_eviction(self):
        """Old entries are cleaned up during check (amortized eviction)."""
        limiter = RateLimiter(max_attempts=5, window_seconds=10, evict_after=20)

        with mock.patch("modules.rate_limiter.time.monotonic") as mock_mono:
            # Add entry at t=0
            mock_mono.return_value = 0.0
            limiter.check("stale-client")
            assert "stale-client" in limiter._counts

            # Advance past evict_after (20s)
            mock_mono.return_value = 25.0
            # Any check triggers eviction of stale entries
            limiter.check("fresh-client")

            assert "stale-client" not in limiter._counts
            assert "fresh-client" in limiter._counts

    def test_independent_keys(self):
        """Different keys are tracked independently."""
        limiter = RateLimiter(max_attempts=1, window_seconds=60)
        assert limiter.check("alice") is None  # 1st for alice
        # Alice is now at limit
        result = limiter.check("alice")
        assert result is not None

        # Bob should still be allowed
        assert limiter.check("bob") is None

    def test_reset_nonexistent_key(self):
        """Resetting a key that doesn't exist is a no-op (no error)."""
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        limiter.reset("never-seen")  # Should not raise
