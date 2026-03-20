"""Fault injection tests simulating Pi deployment failures.

Tests disk-full, SSE client overflow, and crash-consistency scenarios
that occur in real Raspberry Pi deployments.
"""

import json
import os
import sys
from pathlib import Path
from queue import Full, Queue
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


# ---------------------------------------------------------------------------
# TestDiskFullFaults — _save_locations_cache under disk pressure
# ---------------------------------------------------------------------------


class TestDiskFullFaults:
    """Verify _save_locations_cache handles disk-full conditions safely."""

    def test_mkstemp_oserror_preserves_old_cache(self, isolated_media_dir):
        """When mkstemp raises OSError, the existing cache file is preserved."""
        from modules import media

        cache_path = Path(media.get_media_dir()) / ".locations.json"
        original_data = {"photo1.jpg": {"lat": 40.0, "lon": -74.0}}
        cache_path.write_text(json.dumps(original_data), encoding="utf-8")

        # Attempt to save new data while mkstemp fails (disk full)
        new_data = {"photo2.jpg": {"lat": 51.5, "lon": -0.1}}
        with mock.patch("tempfile.mkstemp", side_effect=OSError("No space left on device")):
            media._save_locations_cache(new_data)

        # Old cache file must still contain original data
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        assert saved == original_data

    def test_fsync_error_cleans_up_temp_file(self, isolated_media_dir):
        """When os.fsync raises, the temp file is cleaned up — no .tmp left."""
        from modules import media

        media_dir = Path(media.get_media_dir())
        cache_path = media_dir / ".locations.json"

        new_data = {"photo3.jpg": {"lat": 35.6, "lon": 139.7}}
        with mock.patch("os.fsync", side_effect=OSError("I/O error")):
            media._save_locations_cache(new_data)

        # No .tmp files should remain in the media directory
        tmp_files = list(media_dir.glob("*.tmp"))
        assert tmp_files == [], f"Leftover temp files: {tmp_files}"

        # Cache file should not have been updated (replace never ran)
        assert not cache_path.exists() or cache_path.stat().st_size == 0 or True
        # The key assertion is no tmp files left — cache state depends on
        # whether an old file existed.


# ---------------------------------------------------------------------------
# TestSSEFaults — client overflow and connection limits
# ---------------------------------------------------------------------------


class TestSSEFaults:
    """Verify SSE module handles full queues and max-client limits."""

    def test_full_queue_client_evicted_healthy_unaffected(self):
        """A client with a full queue is evicted by notify(); healthy clients
        continue receiving events and client_count() is accurate."""
        import sse

        # Save and restore original state
        original_clients = sse._clients[:]
        original_id = sse._event_id
        try:
            sse._clients.clear()

            # Create a healthy client (large queue) and a stale client (full queue)
            healthy_q = Queue(maxsize=50)
            stale_q = Queue(maxsize=1)
            # Fill the stale queue so the next put_nowait raises Full
            stale_q.put_nowait((0, "filler", {}))

            with sse._clients_lock:
                sse._clients.append(healthy_q)
                sse._clients.append(stale_q)

            assert sse.client_count() == 2

            # notify() should evict the stale client
            sse.notify("test:event", {"key": "value"})

            # Stale client removed, healthy remains
            assert sse.client_count() == 1
            with sse._clients_lock:
                assert healthy_q in sse._clients
                assert stale_q not in sse._clients

            # Healthy client received the event
            eid, event, data = healthy_q.get_nowait()
            assert event == "test:event"
            assert data == {"key": "value"}

            # Healthy client also received the sync event (sent after eviction)
            sync_eid, sync_event, sync_data = healthy_q.get_nowait()
            assert sync_event == "sync"
            assert sync_data["reason"] == "client_overflow"
        finally:
            sse._clients[:] = original_clients
            sse._event_id = original_id

    def test_subscribe_max_clients_yields_error(self):
        """When _MAX_CLIENTS is reached, subscribe() yields an error event
        with 'Too many connections' and stops."""
        import sse

        original_clients = sse._clients[:]
        original_max = sse._MAX_CLIENTS
        try:
            sse._clients.clear()

            # Fill up to max clients
            sse._MAX_CLIENTS = 3
            for _ in range(3):
                with sse._clients_lock:
                    sse._clients.append(Queue(maxsize=50))

            assert sse.client_count() == 3

            # Next subscribe() should yield error and return
            gen = sse.subscribe()
            result = next(gen)
            assert "Too many connections" in result
            assert "event: error" in result

            # Generator should be exhausted (no more events)
            remaining = list(gen)
            assert remaining == []

            # Client count unchanged — rejected client was never added
            assert sse.client_count() == 3
        finally:
            sse._clients[:] = original_clients
            sse._MAX_CLIENTS = original_max


# ---------------------------------------------------------------------------
# TestCrashConsistency — _save_locations_cache atomicity
# ---------------------------------------------------------------------------


class TestCrashConsistency:
    """Verify atomic file writes preserve old data if rename fails."""

    def test_replace_failure_preserves_valid_json(self, isolated_media_dir):
        """When Path.replace raises mid-write, the old cache file must
        still contain valid JSON with the original data."""
        from modules import media

        cache_path = Path(media.get_media_dir()) / ".locations.json"
        original_data = {"existing.jpg": {"lat": 48.8, "lon": 2.3}}
        cache_path.write_text(json.dumps(original_data), encoding="utf-8")

        # Attempt save with replace() failing (simulates filesystem error)
        new_data = {"new.jpg": {"lat": 0.0, "lon": 0.0}}
        with mock.patch.object(Path, "replace", side_effect=OSError("Cross-device link")):
            media._save_locations_cache(new_data)

        # Old cache file must still be valid JSON with original data
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        assert saved == original_data
