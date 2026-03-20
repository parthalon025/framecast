"""Reusable in-memory rate limiter with amortized cleanup."""
from __future__ import annotations

import threading
import time
from typing import Any


class RateLimiter:
    """Thread-safe sliding-window rate limiter.

    Args:
        max_attempts: Maximum requests allowed within the window.
        window_seconds: Duration of the rate-limit window.
        evict_after: Seconds after which stale entries are purged
                     (defaults to 2x window).
    """

    def __init__(self, max_attempts: int, window_seconds: int, evict_after: int | None = None) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.evict_after = evict_after or (window_seconds * 2)
        self._counts: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        """Check if *key* is rate-limited.

        Returns the number of seconds until the window resets (retry_after)
        if over the limit, or None if under.
        """
        now = time.monotonic()
        with self._lock:
            # Amortized eviction of stale entries
            stale = [k for k, v in self._counts.items() if now - v["start"] > self.evict_after]
            for k in stale:
                del self._counts[k]

            record = self._counts.get(key)
            if record is None:
                self._counts[key] = {"count": 1, "start": now}
                return None

            elapsed = now - record["start"]
            if elapsed > self.window:
                self._counts[key] = {"count": 1, "start": now}
                return None

            record["count"] += 1
            if record["count"] > self.max_attempts:
                return int(self.window - elapsed) + 1
            return None

    def reset(self, key: str) -> None:
        """Reset the counter for *key* (e.g. after successful auth)."""
        with self._lock:
            self._counts.pop(key, None)
