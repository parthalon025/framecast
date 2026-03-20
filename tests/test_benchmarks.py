"""Performance benchmarks for FrameCast hot-path functions.

Uses pytest-benchmark. Thresholds are set for Raspberry Pi 3 (~1 GHz ARM).
On x86 workstations these will pass with wide margin.

Run:
    python3 -m pytest tests/test_benchmarks.py --benchmark-only -v
"""

import os
import sys

import pytest

pytest.importorskip("pytest_benchmark")

# Add app directory to sys.path (same pattern as conftest.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


# ---------------------------------------------------------------------------
# Media function benchmarks
# ---------------------------------------------------------------------------


class TestMediaBenchmarks:
    """Benchmarks for media module hot-path functions."""

    def test_format_size_throughput(self, benchmark):
        """format_size() x 100,000 calls < 2s on Pi 3."""
        from modules.media import format_size

        def run():
            for i in range(100_000):
                format_size(i * 1024)

        benchmark.pedantic(run, rounds=3)
        assert benchmark.stats["mean"] < 2.0, (
            f"format_size mean {benchmark.stats['mean']:.3f}s exceeds 2s threshold"
        )

    def test_hamming_distance_throughput(self, benchmark):
        """hamming_distance() x 100,000 calls < 1s on Pi 3."""
        from modules.media import hamming_distance

        hash_a = "a1b2c3d4e5f60718"
        hash_b = "18076f5e4d3c2b1a"

        def run():
            for _ in range(100_000):
                hamming_distance(hash_a, hash_b)

        benchmark.pedantic(run, rounds=3)
        assert benchmark.stats["mean"] < 1.0, (
            f"hamming_distance mean {benchmark.stats['mean']:.3f}s exceeds 1s threshold"
        )

    def test_allowed_file_throughput(self, benchmark):
        """allowed_file() x 100,000 calls < 2s on Pi 3."""
        from modules.media import allowed_file

        filenames = [
            "photo.jpg", "video.mp4", "document.pdf",
            "image.png", "clip.avi", "readme.txt",
            "sunset.webp", "movie.mkv", "notes.doc",
            "portrait.tiff",
        ]

        def run():
            for i in range(100_000):
                allowed_file(filenames[i % len(filenames)])

        benchmark.pedantic(run, rounds=3)
        assert benchmark.stats["mean"] < 2.0, (
            f"allowed_file mean {benchmark.stats['mean']:.3f}s exceeds 2s threshold"
        )


# ---------------------------------------------------------------------------
# SSE benchmarks
# ---------------------------------------------------------------------------


class TestSSEBenchmarks:
    """Benchmarks for SSE notification dispatch."""

    def test_notify_throughput(self, benchmark):
        """notify() x 100 calls to 10 clients < 50ms."""
        import sse
        from queue import Queue

        # Set up 10 connected clients
        with sse._clients_lock:
            sse._clients.clear()
            for _ in range(10):
                sse._clients.append(Queue(maxsize=sse._MAX_QUEUE_SIZE))

        try:
            def run():
                for i in range(100):
                    sse.notify("benchmark:event", {"index": i})

            benchmark.pedantic(run, rounds=5)
            assert benchmark.stats["mean"] < 0.05, (
                f"notify mean {benchmark.stats['mean']*1000:.1f}ms exceeds 50ms threshold"
            )
        finally:
            # Clean up SSE clients to avoid polluting other tests
            with sse._clients_lock:
                sse._clients.clear()
