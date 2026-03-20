# FrameCast Audit Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all findings from the 11-agent comprehensive audit (2026-03-20) — 100+ findings across backend, frontend, security, CSS, infrastructure, data model, tests, atmosphere, API, silent failures, and mobile design.

**Architecture:** 10 batches ordered by blast radius. Each batch is independently deployable. TDD for all code changes. Batch 1 fixes user-facing bugs that block core functionality. Later batches harden, polish, and add coverage.

**Tech Stack:** Python/Flask, Preact/JSX, CSS, SQLite, systemd, pi-gen, superhot-ui

**Audit agents:** Backend, Frontend, Security, Silent Failure Hunter, CSS, Test Analyzer, Atmosphere, Infra/Shell, API/Routes, Data Model, Mobile Design

---

## Batch 1: Critical Functional Bugs

These block core usage — users locked out, slideshow broken, crashes.

### Task 1.1: Fix PinGate 6-digit PIN lockout

**Files:**
- Modify: `app/frontend/src/components/PinGate.jsx`
- Test: Manual — set PIN_LENGTH=6 in .env, verify 6-digit entry works

Three places hardcode `4` instead of using `pinLength` state. Users with 6-digit PINs are completely locked out.

**Step 1: Fix handleInput truncation**

In `PinGate.jsx`, find `handleInput` callback (~line 101):
```jsx
// BEFORE:
const val = evt.target.value.replace(/\D/g, "").slice(0, 4);
// AFTER:
const val = evt.target.value.replace(/\D/g, "").slice(0, pinLength);
```
And add `pinLength` to the dependency array:
```jsx
// BEFORE:
}, []);
// AFTER:
}, [pinLength]);
```

**Step 2: Fix button disabled check**

Find the VERIFY button (~line 163):
```jsx
// BEFORE:
disabled={pinValue.length !== 4 || verifying}
// AFTER:
disabled={pinValue.length !== pinLength || verifying}
```

**Step 3: Fix button styling conditions**

Find opacity/color conditions (~lines 168-170) — replace all `pinValue.length === 4` with `pinValue.length === pinLength`.

**Step 4: Build and verify**

Run: `cd app/frontend && npm run build`
Expected: Build succeeds, no errors.

**Step 5: Commit**
```bash
git add app/frontend/src/components/PinGate.jsx
git commit -m "fix: PinGate hardcoded 4-digit PIN length — 6-digit PINs now work"
```

---

### Task 1.2: Fix SIGALRM crash with gthread workers

**Files:**
- Modify: `app/web_upload.py`

`signal.SIGALRM` crashes with `ValueError: signal only works in main thread` when gthread dispatches to non-main threads.

**Step 1: Add thread guard to request_timeout decorator**

Find the `request_timeout` decorator (~line 190):
```python
import threading

def request_timeout(seconds):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # SIGALRM only works in main thread — skip timeout in worker threads
            if threading.current_thread() is not threading.main_thread():
                return f(*args, **kwargs)
            # ... existing SIGALRM logic ...
```

**Step 2: Verify build**

Run: `cd app && python3 -c "from web_upload import app; print('OK')"`

**Step 3: Commit**
```bash
git add app/web_upload.py
git commit -m "fix: guard SIGALRM timeout against non-main threads (gthread safety)"
```

---

### Task 1.3: Cap stats buffer to prevent OOM on persistent DB errors

**Files:**
- Modify: `app/modules/db.py`
- Test: `tests/test_db.py`

When `_flush_stats` fails, it re-queues the entire batch. Persistent errors cause unbounded buffer growth → OOM on 1GB Pi.

**Step 1: Write failing test**

In `tests/test_db.py`:
```python
def test_stats_buffer_cap_on_persistent_error(initialized_db, monkeypatch):
    """Stats buffer should not grow unboundedly on persistent flush errors."""
    db_mod = initialized_db
    # Fill buffer beyond cap
    for i in range(600):
        db_mod.record_view(1)
    # Buffer should be capped, not 600
    assert len(db_mod._stats_buffer) <= 500
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db.py::test_stats_buffer_cap_on_persistent_error -v`

**Step 3: Add buffer cap constant and enforce in _flush_stats**

In `db.py`, near `_STATS_FLUSH_THRESHOLD`:
```python
_MAX_STATS_BUFFER = 500  # Cap to prevent OOM on persistent DB errors
```

In `_flush_stats`, in the `except` block where batch is re-queued (~line 607):
```python
except Exception:
    log.error("STATS: flush failed, re-queuing %d entries", len(batch), exc_info=True)
    with _stats_buffer_lock:
        if len(_stats_buffer) < _MAX_STATS_BUFFER:
            _stats_buffer.extend(batch)
        else:
            log.error("STATS: buffer full (%d), dropping %d entries to prevent OOM",
                       len(_stats_buffer), len(batch))
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db.py::test_stats_buffer_cap_on_persistent_error -v`

**Step 5: Commit**
```bash
git add app/modules/db.py tests/test_db.py
git commit -m "fix: cap stats buffer at 500 entries to prevent OOM on persistent DB errors"
```

---

### Task 1.4: Fix slideshow excluding older photos (LIMIT 500)

**Files:**
- Modify: `app/modules/db.py`
- Modify: `app/modules/rotation.py`
- Test: `tests/test_rotation.py`

`get_photos()` has `LIMIT 500` — slideshow silently ignores all photos older than the 500 most recent.

**Step 1: Add `get_playlist_candidates()` to db.py**

Add a new function that returns all eligible photos for rotation (no LIMIT):
```python
def get_playlist_candidates():
    """Get all non-quarantined, non-hidden photos for slideshow rotation."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            """SELECT id, filename, uploaded_at, exif_date, is_favorite, view_count
               FROM photos WHERE quarantined = 0 AND is_hidden = 0"""
        ).fetchall()
        return [dict(r) for r in rows]
```

**Step 2: Update rotation.py to use new function**

In `generate_playlist()`, change the call from `db.get_photos()` to `db.get_playlist_candidates()`.

**Step 3: Write test**

In `tests/test_rotation.py`:
```python
def test_playlist_includes_old_photos(initialized_db):
    """Slideshow should include photos beyond the 500 most recent."""
    db_mod = initialized_db
    # Insert 600 photos
    for i in range(600):
        db_mod.insert_photo(f"photo_{i:04d}.jpg", 100, 100, 100)
    candidates = db_mod.get_playlist_candidates()
    assert len(candidates) == 600
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_rotation.py -v`

**Step 5: Commit**
```bash
git add app/modules/db.py app/modules/rotation.py tests/test_rotation.py
git commit -m "fix: slideshow now includes all photos, not just 500 most recent"
```

---

### Task 1.5: Fix SSE event ID mismatch (broken reconnection replay)

**Files:**
- Modify: `app/sse.py`

`notify()` assigns one event ID, but `subscribe()` generator assigns a different one. Client reconnects with wrong ID → events replayed or missed.

**Step 1: Pass event ID through the queue**

In `notify()`, change the queue put to include the ID:
```python
# BEFORE:
q.put_nowait((event, data))
# AFTER:
q.put_nowait((eid, event, data))
```

In `subscribe()` generator, use the passed ID instead of generating a new one:
```python
# BEFORE:
event, data = q.get(timeout=...)
eid = _next_event_id()
# AFTER:
eid, event, data = q.get(timeout=...)
```

**Step 2: Verify build**

Run: `cd app && python3 -c "from sse import sse_manager; print('OK')"`

**Step 3: Commit**
```bash
git add app/sse.py
git commit -m "fix: SSE event IDs now consistent between notify and subscribe (reconnection works)"
```

---

### Task 1.6: Fix users.py NULL on empty DB + broken test imports

**Files:**
- Modify: `app/modules/users.py`
- Modify: `tests/test_users.py`

`SUM(CASE WHEN ...)` returns NULL on empty table. Also 5 tests reference non-existent `_format_bytes`.

**Step 1: Fix NULL in get_full_stats**

In `users.py` (~line 79), wrap video/photo counts with COALESCE:
```sql
COALESCE(SUM(CASE WHEN is_video = 1 THEN 1 ELSE 0 END), 0) as video_count,
COALESCE(SUM(CASE WHEN is_video = 0 THEN 1 ELSE 0 END), 0) as photo_count
```

**Step 2: Fix test imports**

In `tests/test_users.py`, change `_format_bytes` references to import `format_size` from `modules.media`:
```python
from modules.media import format_size
# Replace: users_mod._format_bytes(...)
# With: format_size(...)
```

**Step 3: Run tests**

Run: `python3 -m pytest tests/test_users.py -v`
Expected: All pass (previously 6 failures → 0)

**Step 4: Commit**
```bash
git add app/modules/users.py tests/test_users.py
git commit -m "fix: NULL stats on empty DB + fix test_users import for format_size"
```

---

## Batch 2: TV Display Resilience

The TV goes black/frozen with no recovery path — critical for a non-technical user.

### Task 2.1: Slideshow infinite retry with visible indicator

**Files:**
- Modify: `app/frontend/src/display/Slideshow.jsx`

After 5 failed inits, slideshow gives up permanently. Add indefinite retry with visible status.

**Step 1: Change retry logic**

In the `init()` function catch block (~line 376), remove the retry count limit:
```jsx
} catch (err) {
    console.error("Slideshow: init failed (attempt %d)", retryCount + 1, err);
    if (!cancelled) {
        const delay = Math.min(1000 * Math.pow(2, retryCount), 60000);
        setTimeout(() => { if (!cancelled) init(retryCount + 1); }, delay);
    }
}
```

**Step 2: Add connection status signal**

Add a module-level signal for connection health:
```jsx
const connectionLost = signal(false);
const lastSuccessfulFetch = signal(Date.now());
```

Set `connectionLost.value = true` when retries exceed 3, and `false` on success.

**Step 3: Render connection lost overlay**

When `connectionLost.value === true`, show a subtle overlay:
```jsx
{connectionLost.value && (
    <div class="fc-connection-lost">CONNECTION LOST — RETRYING</div>
)}
```

**Step 4: Same pattern for playlist refresh failures**

In `fetchPlaylist` catch, track consecutive failures. After 3, set `connectionLost.value = true`. On success, clear it.

**Step 5: Build and verify**

Run: `cd app/frontend && npm run build`

**Step 6: Commit**
```bash
git add app/frontend/src/display/Slideshow.jsx
git commit -m "fix: slideshow retries indefinitely with visible CONNECTION LOST indicator"
```

---

### Task 2.2: DisplayRouter — use createSSE with backoff

**Files:**
- Modify: `app/frontend/src/display/DisplayRouter.jsx`

Replace raw `EventSource` with the shared `createSSE` helper that has exponential backoff.

**Step 1: Import and replace**

```jsx
import { createSSE } from "../lib/sse.js";
```

Replace the manual `new EventSource` + `onerror` reconnection with:
```jsx
const source = createSSE("/api/events", {
    onEvent: { /* existing event handlers */ },
    onError: () => console.warn("DisplayRouter: SSE connection lost"),
});
```

**Step 2: Add connection timeout indicator**

After 30 seconds without SSE, show a subtle "OFFLINE" indicator in the display corner.

**Step 3: Build and verify**

Run: `cd app/frontend && npm run build`

**Step 4: Commit**
```bash
git add app/frontend/src/display/DisplayRouter.jsx
git commit -m "fix: DisplayRouter uses createSSE with exponential backoff"
```

---

### Task 2.3: Bundle Leaflet CSS locally

**Files:**
- Modify: `app/frontend/src/pages/Map.jsx`
- Modify: `app/frontend/package.json`

Leaflet CSS loaded from unpkg CDN — breaks on offline/isolated Pi.

**Step 1: Add leaflet CSS to postbuild**

In `package.json`, add to the postbuild script:
```json
"postbuild": "cp node_modules/superhot-ui/dist/superhot.css ../static/css/superhot.css && cp node_modules/leaflet/dist/leaflet.css ../static/css/leaflet.css"
```

**Step 2: Update Map.jsx**

Remove the CDN URL constant and dynamic `<link>` injection. Add to `spa.html`:
```html
<link rel="stylesheet" href="/static/css/leaflet.css">
```
Or load from static in the component.

**Step 3: Build and verify**

Run: `cd app/frontend && npm run build`
Verify: `ls ../static/css/leaflet.css`

**Step 4: Commit**
```bash
git add app/frontend/src/pages/Map.jsx app/frontend/package.json
git commit -m "fix: bundle Leaflet CSS locally — works on offline Pi"
```

---

## Batch 3: Security Fixes

### Task 3.1: Block quarantine access via /media/ route

**Files:**
- Modify: `app/web_upload.py`

**Step 1: Add guard**

In the `serve_media` route (~line 662):
```python
@app.route("/media/<path:filename>")
def serve_media(filename):
    if filename.startswith(("quarantine/", "quarantine\\")):
        abort(404)
    return send_from_directory(MEDIA_DIR, filename, mimetype=None)
```

**Step 2: Commit**
```bash
git add app/web_upload.py
git commit -m "security: block access to quarantined files via /media/ route"
```

---

### Task 3.2: Validate schedule_days setting

**Files:**
- Modify: `app/api.py`

**Step 1: Add validation**

In the settings update handler, add validation for `schedule_days`:
```python
if key == "schedule_days":
    import re
    if not re.match(r'^[0-6](,[0-6])*$', str(value)):
        return jsonify({"error": f"Invalid schedule_days: {value}"}), 400
```

**Step 2: Commit**
```bash
git add app/api.py
git commit -m "security: validate schedule_days as comma-separated integers 0-6"
```

---

### Task 3.3: Expose public API for db write lock

**Files:**
- Modify: `app/modules/db.py`
- Modify: `app/web_upload.py`
- Modify: `app/modules/users.py`

External modules use `db._write_lock` directly — encapsulation violation.

**Step 1: Add public functions to db.py**

```python
def unquarantine_photo(photo_id, file_size, width, height, checksum, gps_lat, gps_lon):
    """Clear quarantine and update metadata after successful processing."""
    with _write_lock:
        with closing(get_db()) as conn:
            conn.execute(
                """UPDATE photos SET quarantined = 0, quarantine_reason = NULL,
                   file_size = ?, width = ?, height = ?,
                   checksum_sha256 = ?, gps_lat = ?, gps_lon = ?
                   WHERE id = ?""",
                (file_size, width, height, checksum, gps_lat, gps_lon, photo_id),
            )
            conn.commit()

def compute_sha256(filepath):
    """Public wrapper for SHA256 computation."""
    return _compute_sha256(filepath)
```

Also add public wrappers for the user operations that currently use `_write_lock` directly.

**Step 2: Update callers**

Replace `db._write_lock` usage in `web_upload.py` and `users.py` with the new public functions.

**Step 3: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=120`

**Step 4: Commit**
```bash
git add app/modules/db.py app/web_upload.py app/modules/users.py
git commit -m "refactor: expose public DB API — stop reaching into _write_lock"
```

---

### Task 3.4: Fix orphan thumbnail cleanup to scan subdirectories

**Files:**
- Modify: `app/modules/media.py`

**Step 1: Change iterdir to rglob**

In `cleanup_orphan_thumbnails()` (~line 126):
```python
# BEFORE:
video_stems = {f.stem for f in media_dir.iterdir() if f.is_file() and ...}
# AFTER:
video_stems = {f.stem for f in media_dir.rglob("*") if f.is_file() and ...}
```

**Step 2: Add logging to the except OSError**

```python
except OSError as exc:
    log.warning("Failed to remove orphan thumbnail %s: %s", thumb, exc)
```

**Step 3: Commit**
```bash
git add app/modules/media.py
git commit -m "fix: orphan thumbnail cleanup scans subdirs + logs failures"
```

---

## Batch 4: CSS Accessibility

### Task 4.1: Add :focus-visible rules for custom interactive elements

**Files:**
- Modify: `app/frontend/src/styles/base.css`

**Step 1: Add focus-visible styles**

Append to `base.css`:
```css
/* Focus indicators for custom interactive elements */
.fc-day-btn:focus-visible,
.fc-ctx-item:focus-visible,
.fc-btn-primary:focus-visible,
.fc-action-btn:focus-visible {
    outline: 2px solid var(--sh-phosphor);
    outline-offset: 2px;
}
```

**Step 2: Build and verify**

Run: `cd app/frontend && npm run build`

**Step 3: Commit**
```bash
git add app/frontend/src/styles/base.css
git commit -m "a11y: add :focus-visible rules for all custom interactive elements"
```

---

### Task 4.2: Add forced-colors media query

**Files:**
- Modify: `app/frontend/src/styles/base.css`

**Step 1: Add forced-colors overrides**

Append to `base.css`:
```css
@media (forced-colors: active) {
    .fc-day-btn--active {
        border: 2px solid ButtonText;
        background: Highlight;
        color: HighlightText;
    }
    .fc-offline-banner {
        border: 2px solid Mark;
    }
    .fc-otd-label {
        text-shadow: none;
        border: 1px solid CanvasText;
    }
    .fc-card--favorite {
        border-color: Highlight;
    }
    .fc-btn-primary {
        border: 2px solid ButtonText;
    }
}
```

**Step 2: Build and verify**

Run: `cd app/frontend && npm run build`

**Step 3: Commit**
```bash
git add app/frontend/src/styles/base.css
git commit -m "a11y: add forced-colors overrides for high contrast mode"
```

---

### Task 4.3: Replace hardcoded oklch color with token reference

**Files:**
- Modify: `app/frontend/src/styles/settings.css`

**Step 1: Fix day button active background**

In `settings.css` (~line 93):
```css
/* BEFORE: */
background: oklch(85% 0.18 145 / 0.08);
/* AFTER: */
background: color-mix(in oklch, var(--sh-phosphor) 8%, transparent);
```

**Step 2: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/styles/settings.css
git commit -m "fix: replace hardcoded oklch with color-mix token reference"
```

---

## Batch 5: Atmosphere & piOS Voice

### Task 5.1: Normalize in-progress labels to piOS voice

**Files:**
- Modify: `app/frontend/src/components/PinGate.jsx` — "VERIFYING..." → "STANDBY"
- Modify: `app/frontend/src/pages/Update.jsx` — "CHECKING..." → "STANDBY"
- Modify: `app/frontend/src/pages/Albums.jsx` — "CREATING..." → "STANDBY", "DELETING..." → "STANDBY"
- Modify: `app/frontend/src/components/PhotoGrid.jsx` — "DELETING..." → "STANDBY"
- Modify: `app/frontend/src/pages/Users.jsx` — "DELETING..." → "STANDBY"
- Modify: `app/frontend/src/pages/Settings.jsx` — "SAVING" → "STANDBY"

**Step 1: Replace all in-progress labels**

Search for `"VERIFYING..."`, `"CHECKING..."`, `"CREATING..."`, `"DELETING..."`, `"SAVING"` in button text and replace with `"STANDBY"`.

**Step 2: Tighten modal body text**

- `PhotoGrid.jsx`: "This cannot be undone." → "IRREVERSIBLE."
- `Users.jsx`: "Photos will be reassigned to DEFAULT." → "PHOTOS REASSIGNED TO DEFAULT."
- `Albums.jsx`: "Only the album grouping will be removed." → remove (keep "PHOTOS PRESERVED.")

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/PinGate.jsx app/frontend/src/pages/Update.jsx \
    app/frontend/src/pages/Albums.jsx app/frontend/src/components/PhotoGrid.jsx \
    app/frontend/src/pages/Users.jsx app/frontend/src/pages/Settings.jsx
git commit -m "atmosphere: normalize all in-progress labels to piOS STANDBY voice"
```

---

### Task 5.2: Fix palette violations (gold star, QR canvas, border-radius)

**Files:**
- Modify: `app/frontend/src/components/PhotoCard.jsx` — gold → `var(--sh-phosphor)`
- Modify: `app/frontend/src/components/QRCode.jsx` — `#00ff88` → phosphor hex
- Modify: `app/frontend/src/styles/base.css` — `border-radius: 12px` → `0`
- Modify: `app/frontend/src/styles/display.css` — `border-radius: 8px` → `2px`
- Modify: `app/frontend/src/styles/photos.css` — remove hover background from `.fc-ctx-item`

**Step 1: Fix favorite star color**

In `PhotoCard.jsx` (~line 133):
```jsx
// BEFORE:
color: ${isFav ? "gold" : "rgba(255,255,255,0.5)"}
// AFTER:
color: ${isFav ? "var(--sh-phosphor)" : "var(--sh-dim, rgba(255,255,255,0.3))"}
```

**Step 2: Fix QR canvas color**

In `QRCode.jsx` (~line 42), replace `#00ff88` with `#40d670` (approximate oklch(85% 0.18 145)).

**Step 3: Fix border-radius violations**

- `base.css`: `.sh-dropzone { border-radius: 12px; }` → `border-radius: 0;`
- `display.css`: QR overlay `border-radius: 8px` → `border-radius: 2px;`

**Step 4: Remove context menu hover background**

In `photos.css` (~line 27), remove `background: rgba(255, 255, 255, 0.06);` from `.fc-ctx-item:hover`. Keep the phosphor left-border.

**Step 5: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/PhotoCard.jsx app/frontend/src/components/QRCode.jsx \
    app/frontend/src/styles/base.css app/frontend/src/styles/display.css \
    app/frontend/src/styles/photos.css
git commit -m "atmosphere: fix palette violations — gold, QR hex, border-radius, hover bg"
```

---

### Task 5.3: Set facility state at init + deprecate legacy template

**Files:**
- Modify: `app/frontend/src/app.jsx`
- Modify: `app/web_upload.py` (redirect legacy routes)

**Step 1: Call setFacilityState("normal") at app init**

In `app.jsx`, after `applyCapability(cap)`:
```jsx
import { setFacilityState } from "superhot-ui/js/facility.js";
// After capability detection:
setFacilityState("normal");
```

**Step 2: Redirect legacy template routes to SPA**

In `web_upload.py`, change the `/` route to redirect to `/display` (SPA):
```python
@app.route("/")
def index():
    return redirect("/display")
```

Keep the legacy template accessible at a non-default route (e.g., `/legacy`) if needed for backwards compat.

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/app.jsx app/web_upload.py
git commit -m "atmosphere: set facility state at init + redirect legacy template to SPA"
```

---

## Batch 6: Silent Failure Hardening

### Task 6.1: Add logging to bare exception handlers

**Files:**
- Modify: `app/modules/media.py` — cleanup_orphan_thumbnails, _load_locations_cache
- Modify: `app/modules/config.py` — load_env
- Modify: `app/modules/auth.py` — _get_pin_length invalid value logging

**Step 1: Fix cleanup_orphan_thumbnails**

Already done in Task 3.4.

**Step 2: Fix _load_locations_cache**

In `media.py` (~line 220):
```python
# BEFORE:
except (json.JSONDecodeError, OSError):
    return {}
# AFTER:
except (json.JSONDecodeError, OSError) as exc:
    log.warning("Locations cache corrupt or unreadable, rebuilding: %s", exc)
    return {}
```

**Step 3: Add error handling to config.py load_env**

Wrap file read in try/except:
```python
try:
    with open(ENV_FILE) as f:
        for line in f:
            # ... existing parsing ...
except (OSError, UnicodeDecodeError) as exc:
    log.error("Failed to read .env at %s: %s", ENV_FILE, exc)
```

**Step 4: Add invalid PIN_LENGTH warning in auth.py**

In `_get_pin_length`, after the `length not in (4, 6)` check:
```python
else:
    log.warning("Invalid PIN_LENGTH=%d (must be 4 or 6), defaulting to 4", length)
```

**Step 5: Commit**
```bash
git add app/modules/media.py app/modules/config.py app/modules/auth.py
git commit -m "fix: add logging to all bare exception handlers (Lesson #1418)"
```

---

### Task 6.2: Surface fetch errors to users via toasts

**Files:**
- Modify: `app/frontend/src/pages/Albums.jsx`
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/pages/Users.jsx`
- Modify: `app/frontend/src/pages/Stats.jsx`
- Modify: `app/frontend/src/pages/Map.jsx`

**Step 1: Replace console.warn with toast in Albums actions**

For each `.catch((err) => console.warn(...))` in album CRUD operations, add a ShToast call:
```jsx
.catch((err) => {
    console.warn("Albums: action failed", err);
    showToast("FAULT: " + err.message, "error");
});
```

**Step 2: Same pattern for Upload fetchPhotos**

Show a retry-able error state when initial photo load fails.

**Step 3: Replace raw fetch with fetchWithTimeout in Stats.jsx and Map.jsx**

```jsx
// BEFORE:
return fetch("/api/stats")
// AFTER:
return fetchWithTimeout("/api/stats")
```

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Albums.jsx app/frontend/src/pages/Upload.jsx \
    app/frontend/src/pages/Users.jsx app/frontend/src/pages/Stats.jsx \
    app/frontend/src/pages/Map.jsx
git commit -m "fix: surface fetch errors via toasts + use fetchWithTimeout consistently"
```

---

### Task 6.3: Protect file unlink operations

**Files:**
- Modify: `app/web_upload.py`

**Step 1: Wrap individual file unlinks in delete_all**

In `delete_all` (~line 640):
```python
for f in media_path.iterdir():
    if f.is_file() and f.suffix.lower() in all_ext:
        try:
            f.unlink()
            count += 1
        except OSError as exc:
            log.warning("Failed to delete %s during delete-all: %s", f.name, exc)
```

**Step 2: Wrap thumbnail + file unlink in delete**

In the single-delete handler (~line 596):
```python
try:
    thumb_path = Path(THUMBNAIL_DIR) / (filepath.stem + ".jpg")
    if thumb_path.exists():
        thumb_path.unlink()
except OSError as exc:
    log.warning("Failed to remove thumbnail for %s: %s", filepath.name, exc)

try:
    filepath.unlink()
except OSError as exc:
    log.error("Failed to delete file %s: %s", filepath.name, exc)
    return jsonify({"error": "File deletion failed"}), 500
```

**Step 3: Commit**
```bash
git add app/web_upload.py
git commit -m "fix: protect all file unlink operations with OSError handling"
```

---

### Task 6.4: Fix Update page SSE + stale closure

**Files:**
- Modify: `app/frontend/src/pages/Update.jsx`

**Step 1: Add onerror handler to SSE**

```jsx
evtSource.onerror = () => {
    console.warn("Update: SSE connection lost");
    // If we're in an active install, assume reboot is happening
    if (activeStepRef.current >= 2) {
        setRebooting(true);
    }
};
```

**Step 2: Fix stale closure for error step**

Add a ref to track current step:
```jsx
const activeStepRef = useRef(-1);
// In handleInstall, before each setActiveStep(n):
activeStepRef.current = n;
setActiveStep(n);
// In catch:
setErrorStep(activeStepRef.current >= 0 ? activeStepRef.current : 0);
```

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Update.jsx
git commit -m "fix: Update page SSE error handler + stale closure for error step"
```

---

## Batch 7: Infrastructure Fixes

### Task 7.1: Fix systemd service hardening

**Files:**
- Modify: `systemd/framecast.service`
- Modify: `systemd/framecast-kiosk.service`
- Modify: `systemd/framecast-health.service`

**Step 1: Add ReadWritePaths to framecast.service**

The existing `ProtectSystem=strict` blocks writes to media dir. Add:
```ini
ReadWritePaths=/home/pi/media /home/pi/framecast
```

**Step 2: Fix or remove WatchdogSec**

Remove `WatchdogSec` from both `framecast.service` and `framecast-kiosk.service` until proper watchdog notification (via `sd_notify`) is implemented. Currently systemd kills the services for not pinging the watchdog.

```ini
# Remove these lines:
# WatchdogSec=120
# WatchdogSec=60
```

**Step 3: Add sandboxing to kiosk and health services**

Add to `framecast-kiosk.service`:
```ini
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/home/pi/framecast
```

Add to `framecast-health.service`:
```ini
NoNewPrivileges=true
ProtectHome=read-only
ProtectKernelTunables=true
ReadWritePaths=/opt/framecast /var/lib/framecast
```

**Step 4: Commit**
```bash
git add systemd/
git commit -m "infra: fix service hardening — ReadWritePaths, remove WatchdogSec, sandbox kiosk"
```

---

### Task 7.2: Fix pi-gen missing units and scripts

**Files:**
- Modify: `pi-gen/stage2-framecast/03-system/01-run.sh`

**Step 1: Ensure all 9 systemd units are installed**

Verify all `.service` and `.timer` files from `systemd/` are installed in the pi-gen chroot stage. Add any missing `install` and `systemctl enable` commands.

**Step 2: Verify ExecStart paths match actual script locations**

Cross-reference each service's `ExecStart=` path with the actual file paths in the `app/` directory. Fix any mismatches.

**Step 3: Commit**
```bash
git add pi-gen/
git commit -m "infra: install all systemd units in pi-gen image + fix ExecStart paths"
```

---

## Batch 8: Data Model & API Fixes

### Task 8.1: Add checksum_sha256 index

**Files:**
- Modify: `app/modules/db.py`

**Step 1: Add index in schema**

In the `CREATE TABLE` or migration section:
```python
CREATE INDEX IF NOT EXISTS idx_photos_checksum ON photos(checksum_sha256)
```

Add this to `init_db()` after table creation.

**Step 2: Write test**

```python
def test_checksum_index_exists(initialized_db):
    db_mod = initialized_db
    with closing(db_mod.get_db()) as conn:
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='photos'"
        ).fetchall()
        names = [r["name"] for r in indexes]
        assert "idx_photos_checksum" in names
```

**Step 3: Run tests and commit**
```bash
python3 -m pytest tests/test_db.py -v
git add app/modules/db.py tests/test_db.py
git commit -m "perf: add index on checksum_sha256 for faster duplicate detection"
```

---

### Task 8.2: Emit photo:favorited SSE event + fix delete-all JSON

**Files:**
- Modify: `app/api.py`

**Step 1: Add SSE notification to toggle_photo_favorite**

After the DB toggle succeeds:
```python
sse.notify("photo:favorited", {"id": photo_id, "is_favorite": new_state})
```

**Step 2: Add JSON response path to delete-all**

In the `delete_all` handler, check for XHR:
```python
if request.headers.get("X-Requested-With") == "XMLHttpRequest":
    return jsonify({"status": "ok", "deleted": count})
return redirect("/display")
```

**Step 3: Commit**
```bash
git add app/api.py
git commit -m "fix: emit photo:favorited SSE event + add JSON response to delete-all"
```

---

### Task 8.3: Add quarantined record pruning

**Files:**
- Modify: `app/modules/db.py`

**Step 1: Add prune function**

```python
def prune_quarantined(days=30):
    """Remove quarantined photos older than N days."""
    with _write_lock:
        with closing(get_db()) as conn:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor = conn.execute(
                "DELETE FROM photos WHERE quarantined = 1 AND uploaded_at < ?",
                (cutoff,),
            )
            conn.commit()
            count = cursor.rowcount
            if count:
                log.info("DB: pruned %d quarantined photos older than %d days", count, days)
            return count
```

**Step 2: Call from init_db alongside _prune_old_stats**

**Step 3: Commit**
```bash
git add app/modules/db.py
git commit -m "fix: prune quarantined photos older than 30 days on startup"
```

---

### Task 8.4: Fix index() heavy GPS extraction

**Files:**
- Modify: `app/web_upload.py`

**Step 1: Replace heavy call with lightweight DB query**

```python
# BEFORE:
has_locations = bool(media.get_photo_locations())
# AFTER:
with closing(db.get_db()) as conn:
    has_locations = conn.execute(
        "SELECT 1 FROM photos WHERE gps_lat IS NOT NULL AND quarantined = 0 LIMIT 1"
    ).fetchone() is not None
```

**Step 2: Commit**
```bash
git add app/web_upload.py
git commit -m "perf: replace heavy GPS extraction in index() with lightweight DB query"
```

---

## Batch 9: Test Coverage (Security Surface)

### Task 9.1: Add test_auth.py

**Files:**
- Create: `tests/test_auth.py`

**Tests to write (minimum):**
1. `test_verify_correct_pin` — correct PIN sets auth cookie
2. `test_verify_wrong_pin` — wrong PIN returns 401
3. `test_verify_rate_limited` — too many wrong PINs returns 429
4. `test_empty_pin_open_access` — empty ACCESS_PIN bypasses auth
5. `test_hmac_token_not_raw_pin` — cookie value differs from raw PIN
6. `test_origin_validation_cross_origin` — cross-origin POST blocked

Each test uses Flask test client with `app.test_client()`.

**Commit:**
```bash
git add tests/test_auth.py
git commit -m "test: add auth.py test suite — PIN verify, rate limiting, HMAC, origin"
```

---

### Task 9.2: Add test_rate_limiter.py

**Files:**
- Create: `tests/test_rate_limiter.py`

**Tests to write:**
1. `test_under_limit_allowed` — returns None when under max_attempts
2. `test_over_limit_blocked` — returns retry_after when exceeded
3. `test_window_expiry` — counter resets after window_seconds
4. `test_reset_clears_counter` — explicit reset works
5. `test_stale_eviction` — old entries cleaned up

**Commit:**
```bash
git add tests/test_rate_limiter.py
git commit -m "test: add rate_limiter.py test suite — window, reset, eviction"
```

---

### Task 9.3: Add test_config.py

**Files:**
- Create: `tests/test_config.py`

**Tests to write:**
1. `test_load_env_parses_keyvalue` — basic parsing
2. `test_load_env_strips_quotes` — quoted values
3. `test_load_env_skips_comments` — comments and blanks
4. `test_get_env_override` — env var overrides .env
5. `test_save_atomic_write` — temp file + rename pattern
6. `test_save_preserves_comments` — existing comments survive

**Commit:**
```bash
git add tests/test_config.py
git commit -m "test: add config.py test suite — parsing, atomic writes, env overrides"
```

---

## Batch 10: Component & Cleanup Fixes

### Task 10.1: Move Preact signals to module level

**Files:**
- Modify: `app/frontend/src/components/Lightbox.jsx`
- Modify: `app/frontend/src/components/ShDropzone.jsx`
- Modify: `app/frontend/src/pages/Users.jsx` (UserSelectModal)

Signals created inside component bodies are recreated on every render, causing stale subscribers.

**Step 1: Move signals to module level**

For each component, move `signal()` calls outside the function body:
```jsx
// BEFORE (inside component):
function ShDropzone(props) {
    const state = signal("idle");
    // ...
}

// AFTER (module level):
const dropzoneState = signal("idle");
const dropzoneProgress = signal(0);
const dropzoneError = signal("");

function ShDropzone(props) {
    // Use module-level signals
    // ...
}
```

Reset signals at component mount to handle remounting:
```jsx
useEffect(() => {
    dropzoneState.value = "idle";
    dropzoneProgress.value = 0;
    dropzoneError.value = "";
}, []);
```

**Step 2: Same for Lightbox and UserSelectModal**

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/Lightbox.jsx app/frontend/src/components/ShDropzone.jsx \
    app/frontend/src/pages/Users.jsx
git commit -m "fix: move Preact signals to module level — prevent stale subscriber bugs"
```

---

### Task 10.2: Clean up duplicate test fixtures

**Files:**
- Modify: `tests/test_rotation.py`

**Step 1: Remove duplicate fixtures**

Remove the duplicate `isolated_media_dir`, `db_mod`, and `initialized_db` fixtures from `test_rotation.py`. These duplicate `conftest.py` and create maintenance drift.

**Step 2: Run tests to verify**

Run: `python3 -m pytest tests/ -v --timeout=120`

**Step 3: Commit**
```bash
git add tests/test_rotation.py
git commit -m "cleanup: remove duplicate test fixtures — use conftest.py"
```

---

### Task 10.3: Add connection lost CSS for TV display

**Files:**
- Modify: `app/frontend/src/styles/display.css`

**Step 1: Add connection lost overlay style**

```css
.fc-connection-lost {
    position: fixed;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    font-family: var(--sh-font-mono, monospace);
    font-size: 14px;
    color: var(--sh-threat);
    background: var(--sh-void, #000);
    padding: 8px 16px;
    border: 1px solid var(--sh-threat);
    z-index: 30;
    animation: sh-blink 2s step-end infinite;
}
```

**Step 2: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/styles/display.css
git commit -m "feat: add CONNECTION LOST overlay style for TV display"
```

---

## Batch 11: Mobile UX Fixes

### Task 11.1: Add PWA meta tags to spa.html

**Files:**
- Modify: `app/templates/spa.html`

The SPA template has only a viewport tag. The legacy `index.html` has all the PWA tags. The SPA needs them for Add to Home Screen, status bar color, and install prompts.

**Step 1: Add missing meta tags**

Add to `<head>` in `spa.html`:
```html
<meta name="theme-color" content="#000000">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<link rel="apple-touch-icon" href="/static/icon-180.png">
<meta name="description" content="FrameCast — family photo frame">
```

If `index.html` has a PWA manifest link, copy that too.

**Step 2: Commit**
```bash
git add app/templates/spa.html
git commit -m "mobile: add PWA meta tags to SPA template (theme-color, apple-touch-icon)"
```

---

### Task 11.2: Fix iOS auto-zoom — ensure all inputs are 16px+

**Files:**
- Modify: `app/frontend/src/styles/base.css`

iOS Safari auto-zooms the viewport when focusing an input with `font-size < 16px`. Multiple inputs across Albums, Users, Lightbox, and Onboard trigger this.

**Step 1: Add global minimum font-size rule**

Append to `base.css`:
```css
/* Prevent iOS auto-zoom on input focus (requires >= 16px) */
input[type="text"],
input[type="password"],
input[type="number"],
input[type="search"],
input[type="tel"],
select,
textarea,
.sh-input,
.sh-select {
    font-size: max(16px, 1rem);
}
```

**Step 2: Remove conflicting smaller font-sizes on inputs**

In Albums.jsx inline styles, remove any `fontSize: "0.9rem"` or `fontSize: "0.8rem"` on `<input>` elements — the CSS rule will handle it.

In Lightbox.jsx tag input, remove `fontSize: "0.8rem"`.

**Step 3: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/styles/base.css app/frontend/src/pages/Albums.jsx \
    app/frontend/src/components/Lightbox.jsx
git commit -m "mobile: fix iOS auto-zoom — all inputs 16px minimum font-size"
```

---

### Task 11.3: Enlarge touch targets on filter chips, context menu, favorites, checkbox

**Files:**
- Modify: `app/frontend/src/styles/photos.css`
- Modify: `app/frontend/src/components/PhotoCard.jsx`
- Modify: `app/frontend/src/pages/Upload.jsx`
- Modify: `app/frontend/src/pages/Albums.jsx`

**Step 1: Enlarge context menu items**

In `photos.css`, increase `.fc-ctx-item` padding:
```css
/* BEFORE: */
padding: 8px 14px;
/* AFTER: */
padding: 12px 14px;
min-height: 44px;
display: flex;
align-items: center;
```

**Step 2: Enlarge filter chips**

In Upload.jsx and Albums.jsx, increase chip padding to meet 44px height:
```jsx
// BEFORE:
padding: "4px 10px", fontSize: "0.8rem"
// AFTER:
padding: "10px 14px", fontSize: "0.85rem"
```

**Step 3: Enlarge favorite star and selection checkbox**

In PhotoCard.jsx, increase favorite button:
```jsx
// BEFORE:
fontSize: "1rem", padding: "2px 4px"
// AFTER:
fontSize: "1.2rem", padding: "8px", minWidth: "44px", minHeight: "44px"
```

Selection checkbox — increase size and add padding for larger touch target:
```jsx
// BEFORE:
width: "18px", height: "18px"
// AFTER:
width: "24px", height: "24px", padding: "10px"
```
(The padding creates a 44px touch area around the 24px checkbox.)

**Step 4: Enlarge SWITCH user button**

In Upload.jsx, the SWITCH button with `fontSize: "0.65rem"` is tiny:
```jsx
// BEFORE:
fontSize: "0.65rem", padding: "1px 4px"
// AFTER:
fontSize: "0.75rem", padding: "6px 10px", minHeight: "32px"
```

**Step 5: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/styles/photos.css app/frontend/src/components/PhotoCard.jsx \
    app/frontend/src/pages/Upload.jsx app/frontend/src/pages/Albums.jsx
git commit -m "mobile: enlarge touch targets to meet 44px minimum (chips, favs, checkbox)"
```

---

### Task 11.4: Fix Lightbox — safe area, delete confirmation, video autoplay

**Files:**
- Modify: `app/frontend/src/components/Lightbox.jsx`

**Step 1: Add safe area padding to close button**

The close button is at `top: 8px; right: 12px` — can overlap Dynamic Island. Fix:
```jsx
// BEFORE:
top: "8px", right: "12px"
// AFTER:
top: "calc(8px + env(safe-area-inset-top, 0px))", right: "12px",
minWidth: "44px", minHeight: "44px"
```

**Step 2: Add delete confirmation via ShModal**

Wrap the delete action with confirmation:
```jsx
const handleDeleteAction = useCallback(() => {
    // Instead of directly calling onDelete, set a confirmation state
    pendingDelete.value = photo;
}, [photo]);
```

Add a ShModal confirmation dialog (same pattern as PhotoGrid).

**Step 3: Add `muted` to video autoplay**

Line 221 — add `muted` for iOS autoplay compatibility:
```jsx
<video autoplay muted controls ...>
```

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/components/Lightbox.jsx
git commit -m "mobile: fix Lightbox — safe area, delete confirmation, video muted autoplay"
```

---

### Task 11.5: Fix Map page bottom nav overlap + PhoneLayout dvh

**Files:**
- Modify: `app/frontend/src/pages/Map.jsx`
- Modify: `app/frontend/src/components/PhoneLayout.jsx`

**Step 1: Fix Map container height**

Account for bottom nav + safe area:
```jsx
// BEFORE:
height: calc(100dvh - 72px)
// AFTER:
height: calc(100dvh - 72px - env(safe-area-inset-bottom, 0px))
```

Or better — wrap in `fc-page` class which already handles the bottom padding.

**Step 2: Fix PhoneLayout 100vh → 100dvh**

In PhoneLayout.jsx (~line 78):
```jsx
// BEFORE:
min-height: 100vh
// AFTER:
min-height: 100dvh
```

**Step 3: Fix offline banner safe area**

In `settings.css`, add safe-area-inset-top to the offline banner:
```css
.fc-offline-banner {
    top: env(safe-area-inset-top, 0px);
}
```

**Step 4: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/pages/Map.jsx app/frontend/src/components/PhoneLayout.jsx \
    app/frontend/src/styles/settings.css
git commit -m "mobile: fix Map nav overlap, PhoneLayout dvh, offline banner safe area"
```

---

### Task 11.6: Pause SSE on page background (battery optimization)

**Files:**
- Modify: `app/frontend/src/lib/sse.js`

The phone maintains an open SSE connection that keeps the radio active, draining battery.

**Step 1: Add visibilitychange listener**

In `createSSE` or the SSE manager, pause/resume on visibility:
```javascript
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        source.close();
    } else {
        reconnect();
    }
});
```

This closes the SSE connection when the user backgrounds the browser tab/app and reconnects when they return.

**Step 2: Build and commit**
```bash
cd app/frontend && npm run build
git add app/frontend/src/lib/sse.js
git commit -m "mobile: pause SSE on page background to reduce battery drain"
```

---

## Summary

| Batch | Focus | Tasks | Priority |
|-------|-------|-------|----------|
| 1 | Critical functional bugs | 6 | Must fix — users locked out, crashes, data loss |
| 2 | TV display resilience | 3 | Must fix — TV goes black/frozen |
| 3 | Security fixes | 4 | Should fix — quarantine exposure, validation |
| 4 | CSS accessibility | 3 | Should fix — a11y compliance |
| 5 | Atmosphere & piOS voice | 3 | Should fix — design system coherence |
| 6 | Silent failure hardening | 4 | Should fix — error visibility |
| 7 | Infrastructure | 2 | Should fix — service won't start on Pi |
| 8 | Data model & API | 4 | Nice to have — performance, completeness |
| 9 | Test coverage | 3 | Nice to have — security surface tests |
| 10 | Component & cleanup | 3 | Nice to have — maintenance, polish |
| 11 | Mobile UX | 6 | Should fix — touch targets, iOS compat, PWA |

**Total: 41 tasks across 11 batches**

Agents that found each issue are cross-referenced in the audit report saved alongside this plan.
