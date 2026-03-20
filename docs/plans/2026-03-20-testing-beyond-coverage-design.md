# Testing Beyond Coverage — FrameCast

**Date:** 2026-03-20
**Status:** Approved
**Approach:** Two-wave (Wave 1: Python-side, Wave 2: New toolchains)

## Problem

FrameCast has 221 pytest tests with 100% line coverage across 12 Python modules. Line coverage proves code executed, not that it's correct. 13 failure classes remain undetected:

1. Wrong types
2. Wrong values of correct type
3. Race conditions / deadlocks
4. Business logic errors (weak assertions)
5. Flask dynamic request behavior
6. Performance regressions
7. Pi environment failures (disk, network, memory)
8. Crash mid-operation (power loss, kill)
9. Architectural rule violations
10. SSE event shape drift
11. Frontend component bugs
12. Shell script logic errors
13. Test quality itself

## Principle: Risk-Down, Not Technique-Up

Testing layers are selected by failure cost, not by tool popularity:

| Rank | Failure Mode | Cost | Frequency |
|------|-------------|------|-----------|
| 1 | Bricked device (bad OTA rollback) | Re-flash SD, possible data loss | Rare |
| 2 | Hung single worker (SSE/upload blocks gunicorn) | Frame freezes, no remote fix | Occasional |
| 3 | Silent data loss (DB/file write ordering) | Photo gone, user unaware | Rare |
| 4 | Media pipeline crash (corrupt upload) | Worker restart, brief freeze | Occasional |
| 5 | Frontend/backend drift (event shape change) | Feature silently broken | On change |
| 6 | UI rendering bugs | Visible but non-critical | On change |

## Coverage Matrix

Every failure class maps to at least one detection technique. No uncovered class.

| Failure Class | Layer | Technique |
|---|---|---|
| Wrong types | 1 | mypy --strict |
| Architectural drift | 2 | Fitness function tests (pytest + AST) |
| Wrong runtime values | 3 | Property-based testing (hypothesis) |
| Race conditions / deadlocks | 4 | Stateful property testing + threading stress |
| Performance regressions | 5 | pytest-benchmark with thresholds |
| Flask dynamic behavior | 6 | Extended integration tests |
| Test quality | 7 | Mutation testing (mutmut) |
| Pi environment + crash consistency | 8 | Fault injection (monkeypatch) |
| SSE event shape drift | 9 | JSON Schema contract tests |
| Frontend component bugs | 10 | vitest + @testing-library/preact |
| Shell script logic errors | 11 | bats + extracted functions |

## Wave 1: Python-Side (pip dependencies only)

### Layer 1: Static Type Checking (mypy)

**Dependency:** `mypy`, `types-Flask`, `types-Pillow`
**Scope:** All 14 Python files in `app/modules/` + `sse.py` + `api.py` + `web_upload.py`

**Configuration (`mypy.ini`):**
```ini
[mypy]
python_version = 3.12
strict = true
warn_return_any = true
warn_unused_configs = true
```

**What this covers:**
- Function signatures — argument types, return types, no implicit `Any`
- Null safety — `Optional` makes `None` paths explicit (`extract_gps() -> tuple[float, float] | None`)
- Container types — `Queue[tuple[int, str, dict[str, Any]]]` on SSE queues
- Import structure — flags circular imports and missing modules
- Dead code — unreachable branches after type narrowing

**What this does NOT cover:**
- Runtime values (→ Layer 3)
- Concurrency (→ Layer 4)
- Business logic (→ Layer 7)
- Dynamic Flask behavior (→ Layer 6)
- Performance (→ Layer 5)
- Pi environment (→ Layer 8)

**Integration:** `make typecheck` — on-demand initially, CI gate once clean.

### Layer 2: Architectural Fitness Tests

**Dependency:** None (pure pytest + AST parsing)
**Location:** `tests/test_architecture.py`

**Tests (~10):**
- Modules never import from routes (`web_upload`, `api`)
- All `except` blocks contain a `log.` call before any `return`
- All file writes in modules use `tempfile` + `os.fsync` + `Path.replace` (atomic pattern)
- No direct `_write_lock` access outside `db.py`
- No `h` or `Fragment` as callback parameter names in any `.jsx` file
- `gunicorn.conf.py` has `workers = 1` (mandatory Pi constraint)
- All `create_task` calls have a `done_callback` (Lesson #43)

**What this covers:**
- Convention enforcement — machine-verified, not code-review-dependent
- Import direction — modules → routes is one-way
- Safety patterns — atomic writes, exception logging

**What this does NOT cover:**
- Runtime behavior (→ Layers 3-8)
- Whether the conventions are correct (human judgment)

**Integration:** Runs in main test suite (`pytest tests/test_architecture.py`).

### Layer 3: Property-Based Testing (hypothesis)

**Dependency:** `hypothesis`
**Location:** `tests/test_properties.py`

**Target modules and strategies:**

**`media.py`:**
- `format_size(st.integers(min_value=0, max_value=2**63))` → matches `r"^\d+(\.\d+)? (B|KB|MB|GB|TB)$"`
- `allowed_file(st.text())` → never raises, returns bool
- `compute_dhash()` with valid/corrupt/truncated image bytes → returns hex string or `None`, never raises
- `extract_gps()` with malformed EXIF (bad DMS, missing refs, NaN) → returns valid tuple or `None`, never raises
- `hamming_distance()` with arbitrary hex strings → returns int 0-64, symmetric (`h(a,b) == h(b,a)`)

**`sse.py`:**
- `notify()` with arbitrary event names and data dicts → never raises, queues receive valid tuples
- `_replay_events_after()` with arbitrary `last_id` (negative, huge, non-numeric) → never raises

**`db.py`:**
- FTS5 search with arbitrary query strings (unbalanced quotes, SQL injection, unicode) → returns list, never raises
- Photo metadata with edge-case values (zero-byte, empty filename, future dates, negative coords)

**`rotation.py`:**
- Playlist generation: 0 photos, 1 photo, all favorites, no favorites, all same date

**`auth.py`:**
- PIN validation with arbitrary strings → never raises, returns bool
- HMAC token with arbitrary payloads → deterministic and verifiable

**What this covers:**
- Edge cases humans wouldn't write by hand
- Input robustness — arbitrary user content never crashes the system
- Mathematical properties (symmetry, idempotency, range bounds)

**What this does NOT cover:**
- Concurrency (→ Layer 4)
- Performance (→ Layer 5)
- Whether the correct value is returned (only that it's in valid range)

### Layer 4: Concurrency Testing

**Dependency:** `hypothesis` (stateful module), standard `threading`
**Location:** `tests/test_concurrency.py`

**4a. Stateful property testing (hypothesis.stateful):**

State machine for SSE:
- Actions: `subscribe()`, `notify(event, data)`, client disconnects, `client_count()`
- Invariants:
  - `client_count()` == number of active subscriptions
  - No event lost (every `notify` reaches every non-stale client)
  - Event IDs monotonically increasing
  - `_recent_events` never exceeds `_RECENT_BUFFER_SIZE`

**4b. Threading stress tests:**
- 10 threads calling `notify()` concurrently while 5 threads subscribe/disconnect
- Verify: no deadlock (timeout 10s), no exception in any thread
- `client_count()` matches reality after all threads complete
- `_event_id` monotonically increasing with no gaps under concurrent `_next_event_id()`

**What this covers:**
- Race conditions in `_clients`, `_event_id`, `_recent_events`
- Deadlocks from lock ordering
- Stale client cleanup under contention

**What this does NOT cover:**
- Values (→ Layer 3)
- Pi resource constraints (→ Layer 8)

### Layer 5: Performance Benchmark Tests

**Dependency:** `pytest-benchmark`
**Location:** `tests/test_benchmarks.py`

**Benchmarks with regression thresholds (Pi 3 baseline):**
- `compute_dhash()` on 5MB JPEG → < 2s
- `extract_gps()` on JPEG with full EXIF → < 500ms
- `get_media_files()` with 1,000 files → < 5s
- `get_playlist_candidates()` with 10,000 DB rows → < 1s
- `notify()` to 10 connected clients → < 50ms
- FTS5 search on 10,000-row DB → < 500ms
- `format_size()` × 100,000 calls → < 1s

**What this covers:**
- O(n²) detection via scaling tests
- Regression thresholds tuned to slowest target hardware (Pi 3)

**What this does NOT cover:**
- Correctness (→ Layers 1-4)
- Actual Pi hardware timing (thresholds are estimates — calibrate on device)

**Integration:** `make benchmark` — on-demand, not CI.

### Layer 6: Flask Dynamic Behavior Coverage

**Dependency:** `types-Flask` (for mypy), existing test infrastructure
**Location:** Additions to `tests/test_api_integration.py`

**New tests (~8):**
- Upload with missing `Content-Type` → 400, not 500
- Upload with `filename=""` (empty) → rejected gracefully
- Upload with duplicate filenames → dedup behavior verified
- Multipart form with oversized file → 413 response
- Cookie with tampered HMAC → rejected, not crash
- `request.files` with non-file field name → proper handling
- SSE endpoint with `Last-Event-ID` header → replays buffered events
- SSE endpoint with invalid `Last-Event-ID` (non-numeric, negative) → ignores gracefully

**What this covers:**
- Runtime Flask request/response edge cases
- File upload boundary conditions
- Cookie/session tampering

**What this does NOT cover:**
- Types (→ Layer 1)
- Arbitrary values (→ Layer 3)

### Layer 7: Mutation Testing (mutmut)

**Dependency:** `mutmut`
**Scope:** `app/modules/` + `sse.py`

**Priority targets:**
- `sse.py` — coalescing logic, client cleanup (subtle state machines)
- `rotation.py` — weighting math (off-by-one risk)
- `auth.py` — HMAC comparison (security-critical, zero surviving mutants)
- `media.py` — dhash bit manipulation (silent breakage)

**What this covers:**
- Proves tests detect bugs when code changes
- Identifies weak assertions that pass with wrong values
- Meta-validation of all other test layers

**What this does NOT cover:**
- Everything else — mutation testing validates tests, not code

**Integration:** `make mutate` — on-demand diagnostic.

### Layer 8: Fault Injection + Crash Consistency

**Dependency:** None (monkeypatch + standard library)
**Location:** `tests/test_fault_injection.py`

**Disk constraints:**
- Upload when `shutil.disk_usage()` returns < 10MB free → 507, no partial file
- `_save_locations_cache()` when disk full → atomic write fails cleanly, old cache preserved
- Thumbnail generation when disk full → upload succeeds without thumbnail

**Network constraints:**
- SSE client connection reset → `BrokenPipeError` handled, client removed, others unaffected
- SSE keepalive when client queue Full → stale client evicted, worker not blocked

**Single worker blocking:**
- Slow `PIL.Image.open` + concurrent SSE subscribe → neither blocks the other
- Slow `git` during update check → timeout, doesn't block photo serving

**Crash consistency:**
- `_save_locations_cache` interrupted (mock `os.fsync` to raise) → `.locations.json` is old or new, never corrupt
- DB INSERT succeeds but file write fails → DB row exists, recoverable via quarantine
- Stats buffer flush interrupted → unflushed stats lost (acceptable), DB not corrupted

**What this covers:**
- Pi deployment failures (SD card full, WiFi drop, power loss)
- Single-worker gunicorn constraints
- Atomic write guarantees under failure

**What this does NOT cover:**
- Types (→ Layer 1)
- Values (→ Layer 3)
- Concurrency without faults (→ Layer 4)

## Wave 2: New Toolchains

### Layer 9: SSE Contract Tests (JSON Schema)

**Dependencies:** `jsonschema` (Python, pip), `ajv` (npm devDep)
**Schema location:** `schemas/sse-events/` — one `.json` per event type

**Events:**
- `state:current` — `{connected: boolean, clients: integer}`
- `heartbeat` — `{ts: integer}`
- `sync` — `{reason: string}`
- `error` — `{error: string}`
- `photo:added` — `{id: integer, name: string, ...}`
- `photo:deleted` — `{id: integer}`
- `settings:changed` — `{key: string, value: any}`
- `playlist:refresh` — `{}`

**Python side:** pytest validates all `notify()` call sites emit payloads matching their schema.
**JS side:** vitest validates mock SSE events parsed by `createSSE` listeners match schemas.

**What this covers:**
- Event shape agreement between Python and JavaScript
- New events require a schema file (test fails without one)

**What this does NOT cover:**
- Event delivery reliability (→ Layer 4)
- Event value correctness (→ Layer 3)

### Layer 10: Frontend Unit Tests (vitest + @testing-library/preact)

**Dependencies:** `vitest`, `@testing-library/preact`, `jsdom` or `happy-dom`
**Location:** `app/frontend/src/__tests__/`

**`lib/sse.js` (~8 tests):**
- Connects to URL, attaches named listeners
- Reconnects with exponential backoff on error
- Caps backoff at 60s (`BACKOFF_MAX`)
- Resets backoff on successful open
- Pauses when `document.hidden`, reconnects on foreground
- `close()` prevents further reconnection
- Handles `onOpen` callback

**`components/PinGate.jsx` (~5 tests):**
- Renders PIN input
- Submits PIN, stores token on success
- Shows error on wrong PIN
- Rate limit message after max attempts

**`display/Slideshow.jsx` (~5 tests):**
- Renders current photo
- Transitions to next photo
- Handles empty playlist

**`lib/format.js` (~5 tests):**
- Date formatting edge cases
- Size formatting matches backend `format_size()`

**What this covers:**
- Component rendering correctness
- User interaction flows
- Client-side state management

**What this does NOT cover:**
- Backend integration (→ Layer 6)
- Contract compliance (→ Layer 9)

### Layer 11: Shell Script Tests (bats)

**Dependencies:** `bats-core`, `bats-support`, `bats-assert`, `bats-mock`
**Location:** `tests/shell/`

**Refactoring:** Extract testable functions from `health-check.sh`, `slideshow.sh`, `wifi-manager.sh` into `scripts/lib/` sourceable files. Test logic separately from Pi I/O.

**`health-check.sh` (~10 tests):**
- Valid tag format passes regex
- Invalid tag format (injection attempt) rejected
- Missing rollback signature → refuse rollback
- HMAC mismatch → refuse rollback
- Valid HMAC → proceed to health check
- Flask healthy within timeout → exit 0
- Flask unhealthy after timeout → rollback triggered
- Rollback files cleaned up on all exit paths (trap)
- Missing `FLASK_SECRET_KEY` → error, no rollback

**`slideshow.sh` extracted logic (~5 tests):**
- Playlist URL construction
- Timeout/retry logic
- Error state transitions

**`wifi-manager.sh` extracted logic (~5 tests):**
- AP mode timeout calculation
- Connection state machine transitions
- Fallback when nmcli unavailable

**What this covers:**
- Rollback safety (HMAC validation, tag format, cleanup)
- Shell orchestration logic without Pi hardware
- State machine transitions

**What this does NOT cover:**
- Actual Pi service behavior (→ device smoke-test.sh)
- Runtime nmcli/cec-ctl output parsing (mocked)

## Dependencies Summary

### Wave 1 (pip only):
```
mypy
types-Flask
types-Pillow
hypothesis
pytest-benchmark
mutmut
jsonschema
```

### Wave 2 (pip + npm + system):
```
# pip
jsonschema (already in Wave 1)

# npm (devDependencies in app/frontend/package.json)
vitest
@testing-library/preact
happy-dom
ajv

# system
bats-core
bats-support
bats-assert
bats-mock
```

## Makefile Targets

```makefile
typecheck:    mypy --strict app/modules/ app/sse.py app/api.py app/web_upload.py
benchmark:    pytest tests/test_benchmarks.py --benchmark-only
mutate:       mutmut run --paths-to-mutate=app/modules/,app/sse.py
test-shell:   bats tests/shell/
test-frontend: cd app/frontend && npx vitest run
test-all:     pytest tests/ -v --timeout=120 && $(MAKE) test-frontend && $(MAKE) test-shell
```

## File Inventory

### New files:
- `mypy.ini` — mypy configuration
- `tests/test_architecture.py` — architectural fitness tests
- `tests/test_properties.py` — property-based tests (hypothesis)
- `tests/test_concurrency.py` — stateful + threading stress tests
- `tests/test_benchmarks.py` — performance benchmarks
- `tests/test_fault_injection.py` — disk/network/crash tests
- `tests/test_contracts.py` — SSE schema validation (Python side)
- `tests/shell/test_health_check.bats` — health-check.sh tests
- `tests/shell/test_slideshow_lib.bats` — slideshow extracted logic
- `tests/shell/test_wifi_lib.bats` — wifi-manager extracted logic
- `schemas/sse-events/*.json` — SSE event schemas (8 files)
- `scripts/lib/slideshow-lib.sh` — extracted testable functions
- `scripts/lib/wifi-lib.sh` — extracted testable functions
- `app/frontend/src/__tests__/sse.test.js` — SSE client tests
- `app/frontend/src/__tests__/PinGate.test.jsx` — PinGate tests
- `app/frontend/src/__tests__/Slideshow.test.jsx` — Slideshow tests
- `app/frontend/src/__tests__/format.test.js` — format utility tests
- `app/frontend/src/__tests__/contracts.test.js` — SSE schema validation (JS side)
- `app/frontend/vitest.config.js` — vitest configuration

### Modified files:
- `requirements.txt` — add dev dependencies (or separate `requirements-dev.txt`)
- `app/frontend/package.json` — add vitest + testing-library devDeps
- `tests/test_api_integration.py` — add Layer 6 dynamic behavior tests
- `Makefile` — add typecheck, benchmark, mutate, test-shell, test-frontend, test-all targets
- `scripts/health-check.sh` — source from `scripts/lib/` for extracted functions
- `CLAUDE.md` — update test section with new commands and conventions
