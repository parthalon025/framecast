# FrameCast Reliability Deep Audit — Gaps Beyond the 41-Task Plan

> **Date:** 2026-03-20
> **Auditor:** Opus 4.6 (full codebase read, 6 parallel specialized agents)
> **Scope:** Every `.py`, `.sh`, `.service`, `.timer` file in the project
> **Context:** Supplements the existing `2026-03-20-audit-fixes-plan.md` (41 tasks, 11 batches). This report covers findings the prior audit **missed** — cross-module seam bugs, systems engineering gaps, and deeper failure modes.

---

## Executive Summary

The existing 41-task audit plan is thorough for individual-module bugs. This supplementary audit found **14 additional findings** at module boundaries and in systems-level behavior that the prior audit missed. Of these, **4 are CRITICAL** (could brick the device or cause silent data loss), **5 are HIGH**, and **5 are MEDIUM**.

The most dangerous pattern: several "works in development, fails in production" bugs that only manifest on real Pi hardware with systemd, SD cards, and power loss.

---

## CRITICAL Findings

### C1: Overnight HDMI schedule inverted — display never turns on

**File:** `scripts/hdmi-control.sh:59`
**Prior audit:** Not found

The schedule check logic:
```bash
if [[ $NOW_M -ge $ON_M && $NOW_M -lt $OFF_M ]]; then
    "$0" on
else
    "$0" off
fi
```

If ON_TIME=20:00 and OFF_TIME=06:00 (display on in evening, off overnight), `ON_M=1200 > OFF_M=360`. The condition `$NOW_M >= 1200 && $NOW_M < 360` is **always false**. The display will **never turn on**.

This is a classic time-range wrap-around bug. Any user who sets their display schedule to span midnight will have a permanently off display.

**Fix:**
```bash
if [[ $ON_M -le $OFF_M ]]; then
    # Normal range (e.g., 08:00-22:00)
    [[ $NOW_M -ge $ON_M && $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
else
    # Overnight range (e.g., 20:00-06:00)
    [[ $NOW_M -ge $ON_M || $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
fi
```

---

### C2: DISPLAY_SCHEDULE_DAYS completely ignored — schedule runs every day

**File:** `scripts/hdmi-control.sh` (entire file)
**Related:** `systemd/framecast-schedule.service:8` (EnvironmentFile provides the var)
**Prior audit:** Task 3.2 validates the setting value but never connects it to the shell script

The API lets users configure `DISPLAY_SCHEDULE_DAYS` (e.g., "1,2,3,4,5" for weekdays only). The `framecast-schedule.service` loads the `.env` file via `EnvironmentFile`, making the variable available. But `hdmi-control.sh` **never reads or checks it**. The timer runs every minute and applies the schedule to all 7 days regardless.

A user who sets "weekdays only" will find their display still turning on/off on weekends.

**Fix:** Add day-of-week check to the `check-schedule` case:
```bash
check-schedule)
    SCHEDULE_DAYS="${DISPLAY_SCHEDULE_DAYS:-0,1,2,3,4,5,6}"
    TODAY_DOW=$(date +%w)  # 0=Sunday, 6=Saturday
    if [[ ",$SCHEDULE_DAYS," != *",$TODAY_DOW,"* ]]; then
        exit 0  # Not a scheduled day
    fi
    # ... existing time check ...
```

---

### C3: wifi-manager.service references non-existent script

**File:** `systemd/wifi-manager.service:9`
**Prior audit:** Not found

```ini
ExecStart=/opt/framecast/scripts/wifi-check.sh
```

There is no `wifi-check.sh` in `scripts/`. The existing scripts are `health-check.sh`, `smoke-test.sh`, and `hdmi-control.sh`. This service will fail on every boot with `ENOENT`, which could prevent WiFi provisioning from working.

**Impact:** On a fresh Pi with no WiFi configured, the captive portal may not start, leaving the user with no way to connect the device to their network.

**Fix:** Either create `scripts/wifi-check.sh` or fix the ExecStart path to point to the correct script. Based on the `wifi.py` module design, this script should check for WiFi connectivity and start AP mode if disconnected.

---

### C4: SSE coalesce timeout creates excessive CPU wake on Pi

**File:** `app/sse.py:119`
**Prior audit:** Not found

```python
event, data = q.get(timeout=min(_KEEPALIVE_INTERVAL, _COALESCE_WINDOW))
```

With `_KEEPALIVE_INTERVAL=20` and `_COALESCE_WINDOW=2.0`, this evaluates to `min(20, 2.0) = 2.0`. Every SSE client thread wakes up every **2 seconds** to check for pending coalesced events, even when idle.

With `_MAX_CLIENTS=10`, that's **5 thread wakeups per second** on a Pi 3B with 1 CPU core. Combined with the 1-minute schedule timer and other background threads, this creates measurable CPU overhead and unnecessary SD card journal writes from the logging.

**Fix:** Separate the coalesce window from the keepalive timeout:
```python
try:
    event, data = q.get(timeout=_KEEPALIVE_INTERVAL)
    # ... coalesce logic using time.monotonic() delta ...
except Empty:
    # Flush pending + send keepalive
    ...
```

The coalesce window should be checked via timestamp comparison after an event arrives, not as the queue timeout.

---

## HIGH Findings

### H1: `BaseException` catches prevent graceful shutdown

**Files:** `app/modules/config.py:82`, `app/modules/updater.py:135`
**Prior audit:** Not found

Both atomic write implementations catch `BaseException`:
```python
except BaseException:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
```

`BaseException` includes `KeyboardInterrupt` and `SystemExit`. During a graceful `systemctl stop`:
1. systemd sends SIGTERM to gunicorn
2. Gunicorn raises `SystemExit` in workers
3. If a config save is in progress, the `except BaseException` catches `SystemExit`, cleans up the temp file, then re-raises
4. The re-raise is fine, but the catch delays shutdown and could cause gunicorn to hit the `graceful_timeout` if multiple save operations are queued

**Fix:** Change to `except Exception` (or at minimum `except (OSError, IOError)`). The temp file cleanup should happen in a `finally` block, not in a `BaseException` catch.

---

### H2: `atexit.register(_flush_stats)` registered multiple times

**File:** `app/modules/db.py:202`
**Prior audit:** Not found

`init_db()` calls `atexit.register(_flush_stats)` every time it runs. In testing, `init_db()` may be called multiple times (each test fixture). In production, if the app startup code calls it twice (e.g., during .env self-healing + normal init), the atexit handler fires multiple times.

`_flush_stats` is idempotent (second call sees empty buffer), so this is functionally harmless but:
- Creates multiple timer threads (`_start_flush_timer()` is also called each time)
- Each timer independently calls `_periodic_flush()` every 5 minutes
- Multiple timer threads waste RAM and create unnecessary lock contention

**Fix:** Add a module-level flag:
```python
_initialized = False

def init_db():
    global _initialized
    # ... schema setup ...
    if not _initialized:
        atexit.register(_flush_stats)
        _start_flush_timer()
        _initialized = True
```

---

### H3: Thread-unsafe `_thumbnail_cleanup_last` global

**File:** `app/web_upload.py:800-816`
**Prior audit:** Not found

```python
_thumbnail_cleanup_last = 0

@app.before_request
def _periodic_thumbnail_cleanup():
    global _thumbnail_cleanup_last
    now = time.monotonic()
    if now - _thumbnail_cleanup_last > _THUMBNAIL_CLEANUP_INTERVAL:
        _thumbnail_cleanup_last = now
        # ... cleanup ...
```

With `gthread` (2 threads), two concurrent requests can both read `_thumbnail_cleanup_last`, both pass the `> _THUMBNAIL_CLEANUP_INTERVAL` check, and both run cleanup simultaneously. The `rglob` + `unlink` operations aren't idempotent if they race (one thread deletes a file while the other is iterating).

**Impact:** Benign in most cases (worst: a warning log from `OSError` on double-delete). But on a Pi with a slow SD card, two concurrent `rglob("*")` scans could cause noticeable latency spikes on user requests.

**Fix:** Add a threading.Lock or use an atomic compare-and-swap pattern:
```python
_cleanup_lock = threading.Lock()

@app.before_request
def _periodic_thumbnail_cleanup():
    global _thumbnail_cleanup_last
    if not _cleanup_lock.acquire(blocking=False):
        return  # Another thread is already cleaning
    try:
        now = time.monotonic()
        if now - _thumbnail_cleanup_last > _THUMBNAIL_CLEANUP_INTERVAL:
            _thumbnail_cleanup_last = now
            # ... cleanup ...
    finally:
        _cleanup_lock.release()
```

---

### H4: No WAL checkpoint on clean shutdown

**File:** `app/modules/db.py` (missing from atexit)
**Prior audit:** Not found

The database runs in WAL mode, creating `-wal` and `-shm` sidecar files. On clean shutdown, the `atexit` handler flushes stats but does **not** run `PRAGMA wal_checkpoint(TRUNCATE)`.

Over time (and across power-loss cycles), the WAL file grows. On a Pi 3B with a slow SD card, a large WAL file causes:
- Slower reads (SQLite must check both the WAL and main DB)
- Longer recovery time after power loss
- Wasted SD card space

The backup function (`backup_db()`) does checkpoint before backup, but that's only on-demand.

**Fix:** Add WAL checkpoint to the atexit flush:
```python
def _shutdown_db():
    """Flush stats and checkpoint WAL on clean shutdown."""
    _flush_stats()
    try:
        with closing(get_db()) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log.info("DATABASE: clean shutdown — WAL checkpointed")
    except Exception as exc:
        log.error("DATABASE: WAL checkpoint on shutdown failed: %s", exc)

# In init_db():
atexit.register(_shutdown_db)  # instead of just _flush_stats
```

---

### H5: CSP still allows `unpkg.com` after Leaflet bundling

**File:** `app/web_upload.py:248-254`
**Prior audit:** Task 2.3 bundles Leaflet locally but does NOT update the CSP

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "  # ← stale
    "style-src 'self' 'unsafe-inline' https://unpkg.com"     # ← stale
)
```

After bundling Leaflet CSS locally (Task 2.3 / audit-fixes branch), the `unpkg.com` origin is no longer needed. But it remains in the CSP, allowing any script or style from unpkg.com to load. This is a supply chain attack surface.

**Fix:** Remove `https://unpkg.com` from both `script-src` and `style-src`. The OpenStreetMap tile server can stay in `img-src` since those are map tiles, not code.

---

## MEDIUM Findings

### M1: `Pillow.MAX_IMAGE_PIXELS` set per-call from request threads

**File:** `app/web_upload.py:331`
**Prior audit:** Not found

```python
PILImage.MAX_IMAGE_PIXELS = 50_000_000  # Set on every upload
```

This modifies a module-level attribute from request handler threads. With `gthread` (2 threads), two concurrent uploads write the same value simultaneously. Since it's always `50_000_000`, this is functionally harmless, but it's an anti-pattern that could cause bugs if different upload paths needed different limits.

**Fix:** Set once at module level:
```python
# At module level, after import:
try:
    from PIL import Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = 50_000_000
except ImportError:
    pass
```

---

### M2: Gunicorn `graceful_timeout=120` vs SSE long-lived connections

**File:** `app/gunicorn.conf.py:35`
**Prior audit:** Not found

During a rolling restart (OTA update, systemd restart), gunicorn waits `graceful_timeout=120` seconds for in-flight requests. SSE connections are infinite-duration — they'll always hit the timeout and be forcibly killed.

When this happens, ALL SSE clients disconnect simultaneously, then all reconnect within the SSE backoff window (2-20 seconds). This creates a thundering herd that spikes CPU and memory.

On a Pi 3B with 1GB RAM, 10 simultaneous SSE reconnections (each opening a new DB connection for state) could cause a brief OOM or severe latency spike.

**Fix:** This is an inherent tension with SSE + single-worker architecture. Mitigations:
1. Reduce `_MAX_CLIENTS` from 10 to 5
2. Add jitter to the client-side reconnection delay
3. Consider reducing `graceful_timeout` to 30s (SSE connections are stateless anyway)

---

### M3: `get_stats()` runs 6 separate SQL queries without a transaction

**File:** `app/modules/db.py:653-703`
**Prior audit:** Not found

```python
def get_stats():
    with closing(get_db()) as conn:
        total = conn.execute("SELECT COUNT(*)...").fetchone()["c"]
        favorites = conn.execute("SELECT COUNT(*)...").fetchone()["c"]
        # ... 4 more queries ...
```

These 6 queries run in autocommit mode (no explicit `BEGIN`). If a photo is added or deleted between queries, the counts will be inconsistent (e.g., `total` might not equal `photos + videos`).

**Impact:** Dashboard stats could show briefly inconsistent numbers. Low severity since stats refresh frequently and the inconsistency is transient.

**Fix:** Wrap in an explicit read transaction:
```python
with closing(get_db()) as conn:
    conn.execute("BEGIN")
    try:
        # ... all 6 queries ...
    finally:
        conn.execute("ROLLBACK")  # Read-only, no commit needed
```

---

### M4: `_flush_stats` updates photos one-by-one in a loop

**File:** `app/modules/db.py:596-602`
**Prior audit:** Not found

```python
for photo_id, _dur, _trans in batch:
    conn.execute(
        "UPDATE photos SET view_count = view_count + 1, ... WHERE id = ?",
        (photo_id,),
    )
```

With a batch of 30 entries (flush threshold), this runs 30 individual UPDATE statements. If the same photo appears multiple times in the batch (it frequently will in a slideshow), each UPDATE triggers a WAL write.

**Fix:** Aggregate by photo_id before updating:
```python
from collections import Counter
counts = Counter(photo_id for photo_id, _, _ in batch)
for photo_id, count in counts.items():
    conn.execute(
        "UPDATE photos SET view_count = view_count + ?, "
        "last_shown_at = strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id = ?",
        (count, photo_id),
    )
```

This reduces UPDATE count from N to len(unique_photos), which on a typical slideshow with 50 photos could be 30→15 (50% fewer writes).

---

### M5: health-check.sh uses non-constant-time HMAC comparison

**File:** `scripts/health-check.sh:48`
**Prior audit:** Security agent noted this but it wasn't in the plan

```bash
if [ "$EXPECTED_SIG" != "$ACTUAL_SIG" ]; then
```

Bash string comparison is not constant-time. An attacker who can observe timing differences could theoretically brute-force the HMAC one character at a time.

**Impact:** Extremely low. The attacker would need:
1. Physical access to the Pi
2. Ability to plant a rollback-tag file
3. Ability to measure sub-millisecond timing differences on bash string comparison

In practice, this is a non-issue for a home photo frame. But for completeness:

**Fix (if desired):**
```bash
if ! echo -n "$EXPECTED_SIG" | openssl dgst -sha256 -hmac "$ACTUAL_SIG" | grep -q "$(echo -n "$EXPECTED_SIG" | openssl dgst -sha256 -hmac "$ACTUAL_SIG")"; then
```
Or simply use `openssl dgst -verify` with a double-HMAC pattern to make timing differences irrelevant.

---

## Cross-Cutting Observations

### What the existing audit got right
- All bare `except` blocks identified (Lesson #1418)
- SIGALRM + gthread race (Task 1.2)
- WatchdogSec removal (Task 7.1)
- Stats buffer cap (Task 1.3)
- Public DB API (Task 3.3)
- SSE event ID mismatch (Task 1.5)
- 6-digit PIN lockout (Task 1.1)
- Frontend touch targets and mobile fixes (Batch 11)

### What the existing audit missed (this report)
- **Time-range logic bugs** (C1, C2) — domain logic, not code quality
- **Missing scripts/files** (C3) — cross-reference between systemd and filesystem
- **Performance pathologies** (C4, M4) — require load analysis, not just code review
- **Shutdown/lifecycle issues** (H1, H2, H4) — require understanding of gunicorn + systemd interaction
- **CSP stale entries** (H5) — requires tracking fix dependencies (bundling removes the CDN need → CSP must be updated too)
- **Thread safety at module level** (H3, M1) — requires understanding gthread's threading model

### Pattern: the existing audit was module-scoped
Each agent reviewed files in isolation. The bugs above emerge at **boundaries**: systemd↔shell, shell↔Python, gunicorn↔threading, config↔runtime. This is your Cluster B pattern — each layer passes its own review, but the seams leak.

---

## Recommended Priority Order

1. **C1 + C2** (schedule bugs) — Easy fix, high user impact, combined commit
2. **C3** (missing wifi script) — Creates or fixes the ExecStart path
3. **H5** (CSP tightening) — One-line fix, removes attack surface
4. **H4** (WAL checkpoint on shutdown) — 5-line addition to atexit handler
5. **C4** (SSE coalesce timeout) — Small refactor, measurable CPU reduction
6. **H1** (BaseException → Exception) — Two-line fix in two files
7. **H2** (init_db guard) — Simple flag prevents duplicate timers
8. **H3** (thumbnail cleanup lock) — Prevents race on slow SD cards
9. **M4** (batch stats aggregation) — Reduces SD card writes
10. **M1, M2, M3, M5** — Polish, low urgency

---

## Relationship to Existing Worktree

The `fix/audit-fixes-2026-03-20` worktree has 5 commits on top of main:
1. `cleanup: remove duplicate test fixtures from test_rotation`
2. `mobile: enlarge touch targets to meet 44px minimum`
3. `mobile: fix Lightbox — safe area, delete confirmation, video muted`
4. `mobile: fix Map nav overlap, PhoneLayout dvh, offline banner safe area`
5. `mobile: pause SSE on page background to reduce battery drain`

These are all Batch 11 (mobile) fixes from the existing plan. The findings in this report should be applied on top of (or alongside) the remaining batches in the 41-task plan.
