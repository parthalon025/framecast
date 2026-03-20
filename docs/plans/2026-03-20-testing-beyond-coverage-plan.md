# Testing Beyond Coverage — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 11 testing layers covering 13 failure classes to FrameCast, closing every gap that 100% line coverage misses.

**Architecture:** Two-wave approach. Wave 1 (Batches 1-8) adds Python-side layers using only pip dependencies. Wave 2 (Batches 9-11) adds frontend tests (vitest), shell tests (bats), and SSE contract tests (JSON Schema on JS side). Each batch is one layer, one commit.

**Tech Stack:** mypy, hypothesis, pytest-benchmark, mutmut, jsonschema, vitest, @testing-library/preact, happy-dom, ajv, bats-core

**Design doc:** `docs/plans/2026-03-20-testing-beyond-coverage-design.md`

---

## Wave 1: Python-Side

### Batch 1: Dev Dependencies + Makefile Targets

**Files:**

- Create: `requirements-dev.txt`
- Create: `mypy.ini`
- Modify: `Makefile`

**Step 1: Create requirements-dev.txt**

```
# requirements-dev.txt — testing & type checking (not deployed to Pi)
-r requirements.txt
mypy
types-Flask
types-Pillow
hypothesis
pytest-benchmark
mutmut
jsonschema
```

**Step 2: Create mypy.ini**

```ini
[mypy]
python_version = 3.12
strict = true
warn_return_any = true
warn_unused_configs = true

# Flask and related modules — relax strict for now, tighten incrementally
[mypy-modules.*]
disallow_untyped_defs = true
disallow_incomplete_defs = true
warn_return_any = true

# Third-party stubs not always available
[mypy-PIL.*]
ignore_missing_imports = true
```

**Step 3: Add Makefile targets**

Append to `Makefile` after the existing `test:` target:

```makefile
pytest: ## Run pytest suite
	python3 -m pytest tests/ -v --timeout=120

typecheck: ## Run mypy strict type checking
	python3 -m mypy --config-file mypy.ini app/modules/ app/sse.py

benchmark: ## Run performance benchmarks
	python3 -m pytest tests/test_benchmarks.py --benchmark-only -v

mutate: ## Run mutation testing (on-demand diagnostic)
	python3 -m mutmut run --paths-to-mutate=app/modules/,app/sse.py --tests-dir=tests/

test-all: pytest ## Run all test suites
	@echo "All Python tests passed."
```

**Step 4: Install dev dependencies**

Run: `python3 -m pip install -r requirements-dev.txt`
Expected: All packages install cleanly.

**Step 5: Verify Makefile targets parse**

Run: `cd ~/Documents/projects/framecast && make help`
Expected: New targets (pytest, typecheck, benchmark, mutate, test-all) appear in help output.

**Step 6: Commit**

```bash
git add requirements-dev.txt mypy.ini Makefile
git commit -m "chore: add dev dependencies and Makefile targets for testing-beyond-coverage"
```

---

### Batch 2: Layer 1 — Static Type Checking (mypy)

**Files:**

- Modify: `app/modules/media.py` (add type annotations)
- Modify: `app/sse.py` (add type annotations)
- Modify: `app/modules/auth.py` (add type annotations)
- Modify: `app/modules/rotation.py` (add type annotations)
- Modify: `app/modules/config.py` (add type annotations)
- Modify: `app/modules/rate_limiter.py` (add type annotations)

**Step 1: Add type annotations to media.py**

Key signatures to annotate (do not change logic, only add types):

```python
def get_allowed_extensions() -> tuple[set[str], set[str]]: ...
def get_media_dir() -> str: ...
def allowed_file(filename: str) -> bool: ...
def is_video(filename: str) -> bool: ...
def format_size(size_bytes: float) -> str: ...
def get_media_files() -> list[dict[str, object]]: ...
def get_disk_usage() -> dict[str, object]: ...
def get_storage_breakdown() -> dict[str, object]: ...
def cleanup_orphan_thumbnails() -> int: ...
def fix_orientation(image_path: str | Path) -> bool: ...
def extract_gps(image_path: str | Path) -> tuple[float, float] | None: ...
def compute_dhash(filepath: str | Path, hash_size: int = 8) -> str | None: ...
def hamming_distance(hash1: str | None, hash2: str | None) -> int: ...
def _locations_cache_path() -> Path: ...
def _load_locations_cache() -> dict[str, dict[str, float]]: ...
def _save_locations_cache(cache: dict[str, dict[str, float]]) -> None: ...
def get_photo_locations() -> list[dict[str, object]]: ...
def update_location_cache(filename: str, coords: tuple[float, float] | None) -> None: ...
def remove_from_location_cache(filename: str) -> None: ...
```

**Step 2: Add type annotations to sse.py**

```python
from __future__ import annotations
from typing import Any, Generator

def _next_event_id() -> int: ...
def _get_current_state() -> dict[str, Any]: ...
def _replay_events_after(last_id: int | str | None) -> Generator[str, None, None]: ...
def subscribe(last_event_id: str | None = None) -> Generator[str, None, None]: ...
def notify(event: str, data: dict[str, Any] | None = None) -> None: ...
def client_count() -> int: ...
```

**Step 3: Add type annotations to auth.py, rotation.py, config.py, rate_limiter.py**

Follow the same pattern: annotate all function signatures without changing logic.

**Step 4: Run mypy to verify**

Run: `cd ~/Documents/projects/framecast && make typecheck`
Expected: May have some initial errors to fix. Fix any type errors discovered (these are real bugs that mypy found).

**Step 5: Run existing tests to verify no regressions**

Run: `python3 -m pytest tests/ -v --timeout=120`
Expected: All 221 tests pass.

**Step 6: Commit**

```bash
git add app/modules/*.py app/sse.py
git commit -m "feat(types): add mypy strict annotations to modules + sse — Layer 1"
```

---

### Batch 3: Layer 2 — Architectural Fitness Tests

**Files:**

- Create: `tests/test_architecture.py`

**Step 1: Write the architectural fitness tests**

```python
"""Architectural fitness tests — machine-enforced conventions.

These tests verify FrameCast conventions are followed without relying
on code review. Each test encodes a rule from CLAUDE.md or lessons-db.
"""

import ast
import os
import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent / "app"
MODULES_DIR = APP_DIR / "modules"
FRONTEND_DIR = APP_DIR / "frontend" / "src"


class TestImportDirection:
    """Modules must never import from route files."""

    def test_modules_do_not_import_web_upload(self):
        for py in MODULES_DIR.glob("*.py"):
            source = py.read_text()
            assert "from web_upload" not in source, f"{py.name} imports web_upload"
            assert "import web_upload" not in source, f"{py.name} imports web_upload"

    def test_modules_do_not_import_api(self):
        for py in MODULES_DIR.glob("*.py"):
            source = py.read_text()
            assert "from api" not in source, f"{py.name} imports api"
            assert "import api " not in source, f"{py.name} imports api"


class TestExceptionLogging:
    """All except blocks must log before returning a fallback (Lesson #7)."""

    def test_except_blocks_contain_logging(self):
        violations = []
        for py in list(MODULES_DIR.glob("*.py")) + [APP_DIR / "sse.py"]:
            tree = ast.parse(py.read_text(), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.body:
                    # Check if any statement in the handler calls log.*
                    has_log = False
                    for stmt in ast.walk(node):
                        if isinstance(stmt, ast.Attribute) and isinstance(
                            stmt.value, ast.Name
                        ):
                            if stmt.value.id == "log":
                                has_log = True
                                break
                    # Allow bare `pass` in finally blocks and `except ValueError: return`
                    # Only flag if there's a return/assignment without logging
                    has_return = any(
                        isinstance(s, ast.Return) for s in node.body
                    )
                    if has_return and not has_log:
                        violations.append(
                            f"{py.name}:{node.lineno} — except block returns without logging"
                        )
        assert not violations, "Except blocks without logging:\n" + "\n".join(
            violations
        )


class TestGunicornSingleWorker:
    """Gunicorn must use exactly 1 worker (Lesson #1356)."""

    def test_workers_equals_one(self):
        conf = APP_DIR / "gunicorn.conf.py"
        source = conf.read_text()
        # Find `workers = N` assignment
        match = re.search(r"^workers\s*=\s*(\d+)", source, re.MULTILINE)
        assert match, "workers assignment not found in gunicorn.conf.py"
        assert match.group(1) == "1", f"workers = {match.group(1)}, must be 1"


class TestWriteLockEncapsulation:
    """_write_lock must only be accessed from db.py (Lesson #1335)."""

    def test_write_lock_not_used_outside_db(self):
        for py in MODULES_DIR.glob("*.py"):
            if py.name == "db.py":
                continue
            source = py.read_text()
            assert "_write_lock" not in source, (
                f"{py.name} references _write_lock — use db.py public API"
            )


class TestJsxCallbackParamNames:
    """Never use `h` or `Fragment` as callback params (Lesson #13)."""

    def test_no_h_callback_param_in_jsx(self):
        if not FRONTEND_DIR.exists():
            pytest.skip("Frontend directory not found")
        violations = []
        pattern = re.compile(r"\.(map|filter|forEach|reduce|some|every|find)\(\s*\(?\s*h\s*[,)]")
        for jsx in FRONTEND_DIR.rglob("*.jsx"):
            for i, line in enumerate(jsx.read_text().splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{jsx.name}:{i}")
        assert not violations, "JSX files using `h` as callback param:\n" + "\n".join(violations)
```

**Step 2: Run the architectural tests**

Run: `python3 -m pytest tests/test_architecture.py -v`
Expected: All pass. If any fail, they've found a real convention violation — fix the violation, not the test.

**Step 3: Run full suite to verify no interference**

Run: `python3 -m pytest tests/ -v --timeout=120`
Expected: All tests pass (221 existing + new architectural tests).

**Step 4: Commit**

```bash
git add tests/test_architecture.py
git commit -m "feat(arch): add architectural fitness tests — Layer 2"
```

---

### Batch 4: Layer 3 — Property-Based Testing (hypothesis)

**Files:**

- Create: `tests/test_properties.py`

**Step 1: Write property-based tests**

```python
"""Property-based tests using Hypothesis.

Tests mathematical properties, input robustness, and invariants that
example-based tests miss. Each test generates hundreds of random inputs
and verifies that properties hold for all of them.
"""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


# ---------------------------------------------------------------------------
# media.py properties
# ---------------------------------------------------------------------------


class TestFormatSizeProperties:
    """format_size must always return a valid human-readable string."""

    @given(st.integers(min_value=0, max_value=2**63))
    def test_format_always_matches_pattern(self, size_bytes):
        from modules.media import format_size
        import re

        result = format_size(size_bytes)
        assert isinstance(result, str)
        assert re.match(r"^\d+(\.\d+)? (B|KB|MB|GB|TB)$", result), (
            f"format_size({size_bytes}) = {result!r} doesn't match pattern"
        )

    @given(st.integers(min_value=0, max_value=2**63))
    def test_format_is_deterministic(self, size_bytes):
        from modules.media import format_size

        assert format_size(size_bytes) == format_size(size_bytes)


class TestAllowedFileProperties:
    """allowed_file must never raise, always return bool."""

    @given(st.text(max_size=500))
    def test_never_raises(self, filename):
        from modules.media import allowed_file

        result = allowed_file(filename)
        assert isinstance(result, bool)


class TestHammingDistanceProperties:
    """Hamming distance is a metric: symmetric, bounded, zero for identity."""

    @given(
        st.text(alphabet="0123456789abcdef", min_size=16, max_size=16),
        st.text(alphabet="0123456789abcdef", min_size=16, max_size=16),
    )
    def test_symmetric(self, h1, h2):
        from modules.media import hamming_distance

        assert hamming_distance(h1, h2) == hamming_distance(h2, h1)

    @given(st.text(alphabet="0123456789abcdef", min_size=16, max_size=16))
    def test_identity_is_zero(self, h):
        from modules.media import hamming_distance

        assert hamming_distance(h, h) == 0

    @given(
        st.text(alphabet="0123456789abcdef", min_size=16, max_size=16),
        st.text(alphabet="0123456789abcdef", min_size=16, max_size=16),
    )
    def test_bounded_0_to_64(self, h1, h2):
        from modules.media import hamming_distance

        result = hamming_distance(h1, h2)
        assert 0 <= result <= 64

    @given(st.text(max_size=100))
    def test_returns_64_for_invalid_input(self, bad):
        from modules.media import hamming_distance

        # None or mismatched lengths return max distance
        assert hamming_distance(None, bad) == 64
        assert hamming_distance(bad, None) == 64


# ---------------------------------------------------------------------------
# sse.py properties
# ---------------------------------------------------------------------------


class TestReplayEventsAfterProperties:
    """_replay_events_after must never raise for any input."""

    @given(st.one_of(st.none(), st.integers(), st.text(max_size=100)))
    def test_never_raises(self, last_id):
        import sse

        # Consume the generator fully — should never raise
        list(sse._replay_events_after(last_id))

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_returns_strings(self, last_id):
        import sse

        for item in sse._replay_events_after(last_id):
            assert isinstance(item, str)


class TestNotifyProperties:
    """notify must never raise regardless of event name or data."""

    @given(
        st.text(min_size=1, max_size=200),
        st.fixed_dictionaries(
            {},
            optional={"key": st.text(max_size=50), "count": st.integers()},
        ),
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_never_raises(self, event_name, data):
        import sse

        # Reset module state
        with sse._clients_lock:
            sse._clients.clear()
        sse.notify(event_name, data)


# ---------------------------------------------------------------------------
# db.py properties (FTS5 search)
# ---------------------------------------------------------------------------


class TestSearchPhotosProperties:
    """FTS5 search must never raise for any query string."""

    @given(st.text(max_size=200))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_never_raises(self, query):
        from modules import db

        result = db.search_photos(query)
        assert isinstance(result, list)

    @given(st.text(max_size=0))
    def test_empty_returns_empty(self, query):
        from modules import db

        assert db.search_photos(query) == []


# ---------------------------------------------------------------------------
# auth.py properties
# ---------------------------------------------------------------------------


class TestPinGenerationProperties:
    """Generated PINs must have the requested length and be all-numeric."""

    @given(st.sampled_from([4, 6]))
    def test_correct_length(self, length):
        from modules.auth import generate_pin

        pin = generate_pin(length)
        assert len(pin) == length
        assert pin.isdigit()

    @given(st.sampled_from([4, 6]))
    def test_no_leading_zero(self, length):
        from modules.auth import generate_pin

        pin = generate_pin(length)
        assert pin[0] != "0", f"PIN {pin} has leading zero"


# ---------------------------------------------------------------------------
# rotation.py properties
# ---------------------------------------------------------------------------


class TestComputeWeightProperties:
    """Weights must always be positive floats."""

    @given(st.booleans(), st.booleans())
    def test_weight_always_positive(self, is_favorite, recently_shown):
        from modules.rotation import _compute_weight

        photo = {"id": 1, "is_favorite": is_favorite, "uploaded_at": None}
        recent = {1} if recently_shown else set()
        weight = _compute_weight(photo, recent, total_photos=10)
        assert weight > 0
        assert isinstance(weight, float)
```

**Step 2: Run property tests**

Run: `python3 -m pytest tests/test_properties.py -v --timeout=120`
Expected: All pass. Hypothesis will run hundreds of examples per test.

**Step 3: Run full suite**

Run: `python3 -m pytest tests/ -v --timeout=120`
Expected: All tests pass.

**Step 4: Commit**

```bash
git add tests/test_properties.py
git commit -m "feat(properties): add property-based tests for media, sse, db, auth, rotation — Layer 3"
```

---

### Batch 5: Layer 4 — Concurrency Testing

**Files:**

- Create: `tests/test_concurrency.py`

**Step 1: Write concurrency tests**

```python
"""Concurrency tests for SSE module.

Tests thread safety of shared state: _clients, _event_id, _recent_events.
Uses both stateful property testing and direct threading stress tests.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import sse


def _reset_sse_state():
    """Reset SSE module state between tests."""
    with sse._clients_lock:
        sse._clients.clear()
    with sse._event_id_lock:
        sse._event_id = 0
    with sse._recent_lock:
        sse._recent_events.clear()


class TestEventIdMonotonicity:
    """Event IDs must be monotonically increasing under concurrency."""

    def test_concurrent_event_ids_are_unique(self):
        _reset_sse_state()
        ids = []
        lock = threading.Lock()

        def grab_ids(n):
            local = []
            for _ in range(n):
                local.append(sse._next_event_id())
            with lock:
                ids.extend(local)

        threads = [threading.Thread(target=grab_ids, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(ids) == 1000
        assert len(set(ids)) == 1000, "Duplicate event IDs detected"
        assert sorted(ids) == list(range(1, 1001)), "IDs not monotonic"


class TestConcurrentNotify:
    """notify() must be safe under concurrent access."""

    def test_no_exception_under_concurrent_notify(self):
        _reset_sse_state()
        errors = []

        def send_events(n):
            try:
                for i in range(n):
                    sse.notify(f"test:{threading.current_thread().name}", {"i": i})
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=send_events, args=(50,), name=f"sender-{i}")
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors during concurrent notify: {errors}"

    def test_client_count_consistent_after_concurrent_ops(self):
        _reset_sse_state()
        from queue import Queue

        # Add 5 clients
        queues = []
        with sse._clients_lock:
            for _ in range(5):
                q = Queue(maxsize=sse._MAX_QUEUE_SIZE)
                sse._clients.append(q)
                queues.append(q)

        errors = []

        def send_events():
            try:
                for _ in range(100):
                    sse.notify("concurrent:test", {"ts": time.monotonic()})
            except Exception as exc:
                errors.append(exc)

        def remove_client(q):
            try:
                time.sleep(0.01)
                with sse._clients_lock:
                    try:
                        sse._clients.remove(q)
                    except ValueError:
                        pass
            except Exception as exc:
                errors.append(exc)

        # Concurrently send events while removing clients
        send_threads = [threading.Thread(target=send_events) for _ in range(5)]
        remove_threads = [
            threading.Thread(target=remove_client, args=(q,)) for q in queues[:3]
        ]

        for t in send_threads + remove_threads:
            t.start()
        for t in send_threads + remove_threads:
            t.join(timeout=10)

        assert not errors
        assert sse.client_count() == 2  # 5 added, 3 removed


class TestRecentBufferBound:
    """_recent_events must never exceed _RECENT_BUFFER_SIZE."""

    def test_buffer_bounded_under_load(self):
        _reset_sse_state()

        def flood():
            for i in range(200):
                sse.notify(f"flood:{i}", {"n": i})

        threads = [threading.Thread(target=flood) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        with sse._recent_lock:
            assert len(sse._recent_events) <= sse._RECENT_BUFFER_SIZE
```

**Step 2: Run concurrency tests**

Run: `python3 -m pytest tests/test_concurrency.py -v --timeout=30`
Expected: All pass. No deadlocks (timeout would catch them).

**Step 3: Run full suite**

Run: `python3 -m pytest tests/ -v --timeout=120`
Expected: All tests pass.

**Step 4: Commit**

```bash
git add tests/test_concurrency.py
git commit -m "feat(concurrency): add threading stress tests for SSE module — Layer 4"
```

---

### Batch 6: Layer 5 — Performance Benchmarks

**Files:**

- Create: `tests/test_benchmarks.py`

**Step 1: Write benchmark tests**

```python
"""Performance benchmark tests with regression thresholds.

Thresholds are calibrated for Pi 3 (slowest target). Run on workstation
will be faster — the test passes if it's under threshold anywhere.

Run: make benchmark
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

pytest.importorskip("pytest_benchmark")


class TestMediaBenchmarks:
    def test_format_size_100k_calls(self, benchmark):
        from modules.media import format_size

        def run():
            for i in range(100_000):
                format_size(i * 1024)

        result = benchmark(run)
        # Pi 3 threshold: < 2s for 100k calls
        assert benchmark.stats["mean"] < 2.0

    def test_hamming_distance_100k_calls(self, benchmark):
        from modules.media import hamming_distance

        h1 = "a" * 16
        h2 = "b" * 16

        def run():
            for _ in range(100_000):
                hamming_distance(h1, h2)

        benchmark(run)
        assert benchmark.stats["mean"] < 1.0

    def test_allowed_file_100k_calls(self, benchmark):
        from modules.media import allowed_file

        names = ["photo.jpg", "video.mp4", "file.txt", "img.png", "doc.pdf"] * 20_000

        def run():
            for n in names:
                allowed_file(n)

        benchmark(run)
        assert benchmark.stats["mean"] < 2.0


class TestSSEBenchmarks:
    def test_notify_10_clients(self, benchmark):
        import sse
        from queue import Queue

        # Set up 10 clients
        with sse._clients_lock:
            sse._clients.clear()
            for _ in range(10):
                sse._clients.append(Queue(maxsize=sse._MAX_QUEUE_SIZE))

        def run():
            for i in range(100):
                sse.notify("bench:event", {"i": i})

        benchmark(run)
        # Pi 3 threshold: < 50ms for 100 notifications to 10 clients
        assert benchmark.stats["mean"] < 0.05

        # Cleanup
        with sse._clients_lock:
            sse._clients.clear()
```

**Step 2: Run benchmarks**

Run: `cd ~/Documents/projects/framecast && make benchmark`
Expected: All benchmarks pass thresholds. Output shows timing stats.

**Step 3: Commit**

```bash
git add tests/test_benchmarks.py
git commit -m "feat(perf): add performance benchmarks with Pi 3 thresholds — Layer 5"
```

---

### Batch 7: Layer 6 + 8 — Flask Dynamic Behavior + Fault Injection

**Files:**

- Modify: `tests/test_api_integration.py` (add dynamic behavior tests)
- Create: `tests/test_fault_injection.py`

**Step 1: Add Flask dynamic behavior tests to test_api_integration.py**

Append the following test class to `tests/test_api_integration.py`:

```python
class TestFlaskDynamicBehavior:
    """Edge cases in Flask request handling (Layer 6)."""

    def test_upload_empty_filename_rejected(self, client):
        """Upload with filename='' should be rejected gracefully."""
        from io import BytesIO
        data = {"file": (BytesIO(b"fake"), "")}
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code in (400, 422)

    def test_upload_no_file_part(self, client):
        """POST to /upload with no file field should return 400."""
        resp = client.post("/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_sse_invalid_last_event_id_ignored(self, client):
        """SSE with non-numeric Last-Event-ID should not crash."""
        resp = client.get(
            "/api/events",
            headers={"Last-Event-ID": "not-a-number"},
        )
        # SSE endpoint returns streaming response — verify it starts
        assert resp.status_code == 200

    def test_sse_negative_last_event_id_ignored(self, client):
        """SSE with negative Last-Event-ID should not crash."""
        resp = client.get(
            "/api/events",
            headers={"Last-Event-ID": "-999"},
        )
        assert resp.status_code == 200
```

**Step 2: Create fault injection tests**

```python
"""Fault injection tests — simulating Pi deployment failures.

Tests disk full, network drops, crash consistency, and single-worker
blocking scenarios using monkeypatch to simulate hostile environments.
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from queue import Full, Queue
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


class TestDiskFullFaults:
    """Behavior when the SD card is full."""

    def test_save_locations_cache_disk_full_preserves_old(self, tmp_path, monkeypatch):
        """Atomic write on disk full should preserve the old cache."""
        from modules import media

        cache_file = tmp_path / "media" / ".locations.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Write a valid cache first
        old_cache = {"photo1.jpg": {"lat": 40.0, "lon": -74.0}}
        cache_file.write_text(json.dumps(old_cache))

        monkeypatch.setattr(media, "_locations_cache_path", lambda: cache_file)

        # Make tempfile.mkstemp raise (simulating full disk)
        original_mkstemp = tempfile.mkstemp

        def failing_mkstemp(**kwargs):
            raise OSError("No space left on device")

        monkeypatch.setattr(tempfile, "mkstemp", failing_mkstemp)

        # This should log warning but not corrupt the cache
        media._save_locations_cache({"new": {"lat": 0, "lon": 0}})

        # Old cache must still be intact
        assert json.loads(cache_file.read_text()) == old_cache

    def test_save_locations_cache_fsync_failure(self, tmp_path, monkeypatch):
        """If fsync raises, temp file should be cleaned up."""
        from modules import media

        cache_file = tmp_path / "media" / ".locations.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(media, "_locations_cache_path", lambda: cache_file)

        # Make os.fsync raise
        monkeypatch.setattr(os, "fsync", mock.Mock(side_effect=OSError("I/O error")))

        media._save_locations_cache({"test": {"lat": 1, "lon": 2}})

        # No temp files should remain
        tmp_files = list(cache_file.parent.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"


class TestSSEFaults:
    """SSE behavior under network failures."""

    def test_stale_client_evicted_on_full_queue(self):
        """Client with full queue should be evicted, not block notify."""
        import sse

        with sse._clients_lock:
            sse._clients.clear()

        # Create one client with a full queue
        full_q = Queue(maxsize=1)
        full_q.put_nowait((0, "filler", {}))  # Fill it

        # Create one healthy client
        healthy_q = Queue(maxsize=50)

        with sse._clients_lock:
            sse._clients.append(full_q)
            sse._clients.append(healthy_q)

        sse.notify("test:event", {"data": "value"})

        # Stale client should be removed
        assert sse.client_count() == 1
        # Healthy client should have received the event
        assert not healthy_q.empty()

    def test_max_clients_rejected_gracefully(self):
        """Exceeding _MAX_CLIENTS should yield error event, not crash."""
        import sse

        with sse._clients_lock:
            sse._clients.clear()
            # Fill to max
            for _ in range(sse._MAX_CLIENTS):
                sse._clients.append(Queue(maxsize=50))

        # Next subscribe should be rejected
        gen = sse.subscribe()
        first_event = next(gen)
        assert "Too many connections" in first_event

        # Cleanup
        with sse._clients_lock:
            sse._clients.clear()


class TestCrashConsistency:
    """Verify atomic write guarantees under simulated crashes."""

    def test_locations_cache_either_old_or_new(self, tmp_path, monkeypatch):
        """After interrupted write, cache is either old or new, never corrupt."""
        from modules import media

        cache_file = tmp_path / "media" / ".locations.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(media, "_locations_cache_path", lambda: cache_file)

        old_data = {"a.jpg": {"lat": 1.0, "lon": 2.0}}
        cache_file.write_text(json.dumps(old_data))

        new_data = {"b.jpg": {"lat": 3.0, "lon": 4.0}}

        # Simulate crash during rename by making Path.replace raise
        original_replace = Path.replace

        def crashing_replace(self, target):
            raise OSError("Simulated power loss during rename")

        monkeypatch.setattr(Path, "replace", crashing_replace)

        media._save_locations_cache(new_data)

        # Cache must still be valid JSON (old data)
        content = json.loads(cache_file.read_text())
        assert content == old_data, "Cache corrupted after interrupted write"
```

**Step 3: Run fault injection tests**

Run: `python3 -m pytest tests/test_fault_injection.py -v`
Expected: All pass.

**Step 4: Run full suite**

Run: `python3 -m pytest tests/ -v --timeout=120`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add tests/test_fault_injection.py tests/test_api_integration.py
git commit -m "feat(fault): add fault injection + Flask dynamic behavior tests — Layers 6+8"
```

---

### Batch 8: Layer 7 — Mutation Testing Setup

**Files:**

- Create: `setup.cfg` (mutmut configuration)

**Step 1: Create mutmut config**

```ini
[mutmut]
paths_to_mutate = app/modules/auth.py,app/modules/rotation.py,app/modules/media.py,app/sse.py
tests_dir = tests/
runner = python -m pytest tests/ -x -q --timeout=30
```

**Step 2: Run a quick mutation test on auth.py**

Run: `cd ~/Documents/projects/framecast && python3 -m mutmut run --paths-to-mutate=app/modules/auth.py --runner="python3 -m pytest tests/test_auth.py -x -q --timeout=30"`
Expected: Most mutants killed. Note any survivors — these indicate weak assertions to strengthen later.

**Step 3: Commit**

```bash
git add setup.cfg
git commit -m "feat(mutation): add mutmut configuration — Layer 7"
```

---

## Wave 2: New Toolchains

### Batch 9: Layer 9 — SSE Contract Schemas + Python Validation

**Files:**

- Create: `schemas/sse-events/state-current.json`
- Create: `schemas/sse-events/heartbeat.json`
- Create: `schemas/sse-events/sync.json`
- Create: `schemas/sse-events/error.json`
- Create: `schemas/sse-events/photo-added.json`
- Create: `schemas/sse-events/photo-deleted.json`
- Create: `schemas/sse-events/photo-favorited.json`
- Create: `schemas/sse-events/settings-changed.json`
- Create: `schemas/sse-events/slideshow-now-playing.json`
- Create: `schemas/sse-events/slideshow-show.json`
- Create: `schemas/sse-events/update-rebooting.json`
- Create: `tests/test_contracts.py`

**Step 1: Create schema files**

Example `schemas/sse-events/state-current.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "state:current",
  "description": "Initial state sent on SSE connect",
  "type": "object",
  "properties": {
    "connected": {"type": "boolean"},
    "clients": {"type": "integer", "minimum": 0}
  },
  "required": ["connected"]
}
```

Create one schema file per event type, matching the actual payloads from:
- `sse.py` lines 58, 95, 153, 207 → `state:current`, `error`, `heartbeat`, `sync`
- `api.py` lines 354, 511, 549, 725, 739, 1216 → `settings:changed`, `photo:favorited`, `photo:deleted`, `slideshow:now_playing`, `slideshow:show`, `update:rebooting`
- `web_upload.py` lines 635, 699 → `photo:added`, `photo:deleted`

**Step 2: Create Python contract test**

```python
"""SSE contract tests — validate event payloads match JSON schemas.

Loads schemas from schemas/sse-events/ and validates that known
event payloads conform. Both Python emitter and JS consumer test
against the same schemas.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import validate, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

SCHEMA_DIR = Path(__file__).parent.parent / "schemas" / "sse-events"


def load_schema(event_name):
    """Load a JSON Schema file for the given SSE event name."""
    # Convert event name to filename: "state:current" → "state-current.json"
    filename = event_name.replace(":", "-") + ".json"
    schema_path = SCHEMA_DIR / filename
    assert schema_path.exists(), f"No schema for event '{event_name}' at {schema_path}"
    return json.loads(schema_path.read_text())


class TestSSEContractSchemas:
    """Validate that SSE event payloads match their schemas."""

    def test_state_current_schema(self):
        schema = load_schema("state:current")
        validate({"connected": True, "clients": 3}, schema)

    def test_heartbeat_schema(self):
        schema = load_schema("heartbeat")
        validate({"ts": 1711000000}, schema)

    def test_sync_schema(self):
        schema = load_schema("sync")
        validate({"reason": "client_overflow"}, schema)

    def test_error_schema(self):
        schema = load_schema("error")
        validate({"error": "Too many connections"}, schema)

    def test_photo_added_schema(self):
        schema = load_schema("photo:added")
        validate({"filename": "photo.jpg", "photo_id": 42}, schema)

    def test_photo_deleted_schema(self):
        schema = load_schema("photo:deleted")
        validate({"filename": "photo.jpg"}, schema)
        validate({"count": 5}, schema)

    def test_all_events_have_schemas(self):
        """Every SSE event type used in code must have a schema file."""
        known_events = [
            "state:current", "heartbeat", "sync", "error",
            "photo:added", "photo:deleted", "photo:favorited",
            "settings:changed", "slideshow:now_playing",
            "slideshow:show", "update:rebooting",
        ]
        missing = []
        for event in known_events:
            filename = event.replace(":", "-") + ".json"
            if not (SCHEMA_DIR / filename).exists():
                missing.append(event)
        assert not missing, f"Missing schemas for: {missing}"
```

**Step 3: Run contract tests**

Run: `python3 -m pytest tests/test_contracts.py -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add schemas/ tests/test_contracts.py
git commit -m "feat(contracts): add SSE event JSON schemas + Python validation — Layer 9"
```

---

### Batch 10: Layer 10 — Frontend Unit Tests (vitest)

**Files:**

- Modify: `app/frontend/package.json` (add devDeps)
- Create: `app/frontend/vitest.config.js`
- Create: `app/frontend/src/__tests__/sse.test.js`
- Create: `app/frontend/src/__tests__/format.test.js`

**Step 1: Add vitest devDependencies**

In `app/frontend/package.json`, add to `devDependencies`:

```json
{
  "devDependencies": {
    "esbuild": "^0.25.0",
    "vitest": "^3.0.0",
    "happy-dom": "^16.0.0"
  }
}
```

Add to `scripts`:
```json
"test": "vitest run",
"test:watch": "vitest"
```

**Step 2: Create vitest.config.js**

```javascript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "happy-dom",
    include: ["src/__tests__/**/*.test.{js,jsx}"],
  },
});
```

**Step 3: Create SSE client test**

```javascript
// src/__tests__/sse.test.js
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock EventSource
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    MockEventSource.instances.push(this);
  }
  addEventListener(event, handler) {
    this.listeners[event] = handler;
  }
  close() {
    this.closed = true;
  }
}
MockEventSource.instances = [];

beforeEach(() => {
  MockEventSource.instances = [];
  globalThis.EventSource = MockEventSource;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllTimers();
  delete globalThis.EventSource;
});

describe("createSSE", async () => {
  const { createSSE } = await import("../lib/sse.js");

  it("connects to the given URL", () => {
    const sse = createSSE("/api/events");
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toBe("/api/events");
    sse.close();
  });

  it("attaches named event listeners", () => {
    const handler = vi.fn();
    const sse = createSSE("/api/events", {
      listeners: { "photo:added": handler },
    });
    expect(MockEventSource.instances[0].listeners["photo:added"]).toBe(handler);
    sse.close();
  });

  it("calls onOpen callback when connected", () => {
    const onOpen = vi.fn();
    const sse = createSSE("/api/events", { onOpen });
    MockEventSource.instances[0].onopen();
    expect(onOpen).toHaveBeenCalledOnce();
    sse.close();
  });

  it("reconnects with backoff on error", () => {
    const sse = createSSE("/api/events");
    const first = MockEventSource.instances[0];
    first.onerror();
    // After error, should schedule reconnect at 1000ms
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(2);
    sse.close();
  });

  it("doubles backoff on consecutive errors", () => {
    const sse = createSSE("/api/events");
    // First error → 1000ms backoff
    MockEventSource.instances[0].onerror();
    vi.advanceTimersByTime(1000);
    // Second error → 2000ms backoff
    MockEventSource.instances[1].onerror();
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(2); // Not yet reconnected
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(3);
    sse.close();
  });

  it("caps backoff at 60s", () => {
    const sse = createSSE("/api/events");
    // Trigger many errors to max out backoff
    for (let i = 0; i < 10; i++) {
      MockEventSource.instances[MockEventSource.instances.length - 1].onerror();
      vi.advanceTimersByTime(60000);
    }
    sse.close();
    // All should have connected (backoff never exceeds 60s)
    expect(MockEventSource.instances.length).toBeGreaterThan(5);
  });

  it("resets backoff on successful open", () => {
    const sse = createSSE("/api/events");
    // Error → backoff = 1000
    MockEventSource.instances[0].onerror();
    vi.advanceTimersByTime(1000);
    // Success → backoff reset
    MockEventSource.instances[1].onopen();
    // Another error → backoff should be 1000 again (not 2000)
    MockEventSource.instances[1].onerror();
    vi.advanceTimersByTime(1000);
    expect(MockEventSource.instances).toHaveLength(3);
    sse.close();
  });

  it("close() prevents further reconnection", () => {
    const sse = createSSE("/api/events");
    sse.close();
    MockEventSource.instances[0].onerror();
    vi.advanceTimersByTime(60000);
    expect(MockEventSource.instances).toHaveLength(1); // No reconnect
  });
});
```

**Step 4: Install npm deps and run**

Run: `cd ~/Documents/projects/framecast/app/frontend && npm install && npm test`
Expected: All vitest tests pass.

**Step 5: Update Makefile**

Add to `Makefile`:
```makefile
test-frontend: ## Run frontend unit tests (vitest)
	cd app/frontend && npx vitest run
```

Update `test-all`:
```makefile
test-all: pytest test-frontend ## Run all test suites
	@echo "All tests passed."
```

**Step 6: Commit**

```bash
git add app/frontend/package.json app/frontend/vitest.config.js app/frontend/src/__tests__/ Makefile
git commit -m "feat(frontend): add vitest + SSE client tests — Layer 10"
```

---

### Batch 11: Layer 11 — Shell Script Tests (bats)

**Files:**

- Create: `scripts/lib/health-check-lib.sh`
- Modify: `scripts/health-check.sh` (source lib)
- Create: `tests/shell/test_health_check.bats`

**Step 1: Install bats**

Run: `brew install bats-core`
Expected: bats installed.

**Step 2: Extract testable functions from health-check.sh**

Create `scripts/lib/health-check-lib.sh`:

```bash
#!/bin/bash
# health-check-lib.sh — Extracted testable functions from health-check.sh
# Source this file in tests and in health-check.sh.

validate_tag_format() {
    local tag="$1"
    [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

validate_hmac() {
    local tag="$1" secret="$2" actual_sig="$3"
    local expected
    expected=$(echo -n "$tag" | openssl dgst -sha256 -hmac "$secret" | awk '{print $NF}')
    [[ "$expected" == "$actual_sig" ]]
}

read_secret_from_env() {
    local env_file="$1"
    if [ -f "$env_file" ]; then
        grep "^FLASK_SECRET_KEY=" "$env_file" 2>/dev/null | cut -d= -f2- || true
    fi
}
```

**Step 3: Create bats tests**

Create `tests/shell/test_health_check.bats`:

```bash
#!/usr/bin/env bats
# Tests for health-check.sh extracted functions.

setup() {
    source "$BATS_TEST_DIRNAME/../../scripts/lib/health-check-lib.sh"
    TEST_DIR=$(mktemp -d)
}

teardown() {
    rm -rf "$TEST_DIR"
}

@test "validate_tag_format accepts valid semver tag" {
    run validate_tag_format "v1.2.3"
    [ "$status" -eq 0 ]
}

@test "validate_tag_format accepts v0.0.0" {
    run validate_tag_format "v0.0.0"
    [ "$status" -eq 0 ]
}

@test "validate_tag_format rejects missing v prefix" {
    run validate_tag_format "1.2.3"
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects shell injection" {
    run validate_tag_format 'v1.0.0; rm -rf /'
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects empty string" {
    run validate_tag_format ""
    [ "$status" -ne 0 ]
}

@test "validate_tag_format rejects non-numeric" {
    run validate_tag_format "vX.Y.Z"
    [ "$status" -ne 0 ]
}

@test "validate_hmac succeeds with correct signature" {
    SECRET="test-secret-key"
    TAG="v1.0.0"
    SIG=$(echo -n "$TAG" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')
    run validate_hmac "$TAG" "$SECRET" "$SIG"
    [ "$status" -eq 0 ]
}

@test "validate_hmac fails with wrong signature" {
    run validate_hmac "v1.0.0" "secret" "0000000000000000"
    [ "$status" -ne 0 ]
}

@test "read_secret_from_env reads FLASK_SECRET_KEY" {
    echo "FLASK_SECRET_KEY=my-secret" > "$TEST_DIR/.env"
    result=$(read_secret_from_env "$TEST_DIR/.env")
    [ "$result" = "my-secret" ]
}

@test "read_secret_from_env returns empty for missing file" {
    result=$(read_secret_from_env "$TEST_DIR/nonexistent")
    [ -z "$result" ]
}
```

**Step 4: Run bats tests**

Run: `bats tests/shell/test_health_check.bats`
Expected: All tests pass.

**Step 5: Update Makefile**

Add:
```makefile
test-shell: ## Run shell script tests (bats)
	bats tests/shell/
```

Update `test-all`:
```makefile
test-all: pytest test-frontend test-shell ## Run all test suites
	@echo "All tests passed."
```

**Step 6: Modify health-check.sh to source lib**

After `set -euo pipefail`, add:
```bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/health-check-lib.sh"
```

Replace the inline regex check with:
```bash
if ! validate_tag_format "$PREV_TAG"; then
```

**Step 7: Commit**

```bash
git add scripts/lib/ tests/shell/ scripts/health-check.sh Makefile
git commit -m "feat(shell): add bats tests for health-check + extracted lib — Layer 11"
```

---

### Batch 12: Final — Update CLAUDE.md + PR

**Files:**

- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md test section**

Replace the Build section's test line:
```
- Tests: `python3 -m pytest tests/ -v --timeout=120` (160 tests)
```
With:
```
- Tests (Python): `make pytest` (pytest suite, ~250+ tests)
- Tests (Frontend): `make test-frontend` (vitest, SSE + component tests)
- Tests (Shell): `make test-shell` (bats, health-check + wifi + slideshow lib)
- Tests (All): `make test-all` (runs all three suites)
- Type check: `make typecheck` (mypy strict on modules + sse)
- Benchmarks: `make benchmark` (Pi 3 regression thresholds)
- Mutation: `make mutate` (on-demand test quality audit)
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with new test commands and conventions"
```

**Step 3: Push and create PR**

```bash
git push -u origin docs/testing-beyond-coverage-design
gh pr create --title "Testing Beyond Coverage — 11 layers, 13 failure classes" \
  --body "Adds comprehensive testing layers beyond line coverage. See docs/plans/2026-03-20-testing-beyond-coverage-design.md for full design."
```
