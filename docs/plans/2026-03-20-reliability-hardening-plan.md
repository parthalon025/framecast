# FrameCast Reliability Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 25 reliability findings from the deep audit that were missed by the 41-task PR #79 — eliminate all "permanent brick" failure modes and silent data loss paths.

**Architecture:** 8 batches ordered by blast radius. All changes are against the `main` branch (post-PR#79). No frontend/JS changes — this plan is purely backend, systemd, and shell. Each batch is independently deployable. TDD for Python changes.

**Tech Stack:** Python/Flask, bash, systemd, SQLite

---

## Batch 1: Brick Prevention (systemd)

Prevents the device from entering an unrecoverable state that requires physical access to fix.

### Task 1.1: Add StartLimitAction=reboot to prevent permanent service death

**Files:**
- Modify: `systemd/framecast.service`
- Modify: `systemd/framecast-kiosk.service`

Currently `StartLimitBurst=5` in `StartLimitIntervalSec=60` means 5 crashes in 60s permanently kills the service. On a consumer device with no SSH, this is a brick.

**Step 1: Fix framecast.service**

In `systemd/framecast.service`, change:
```ini
StartLimitIntervalSec=60
StartLimitBurst=5
```
to:
```ini
StartLimitIntervalSec=600
StartLimitBurst=10
StartLimitAction=reboot
```

**Step 2: Fix framecast-kiosk.service**

Same change in `systemd/framecast-kiosk.service`.

**Step 3: Commit**
```bash
git add systemd/framecast.service systemd/framecast-kiosk.service
git commit -m "fix: add StartLimitAction=reboot — prevent permanent service death on crash loop"
```

---

### Task 1.2: Change kiosk Requires= to BindsTo= for failure propagation

**Files:**
- Modify: `systemd/framecast-kiosk.service`

`Requires=framecast.service` means if gunicorn dies after kiosk starts, the kiosk keeps running and shows errors. `BindsTo=` propagates stop/failure, so both restart together.

**Step 1: Change directive**

In `systemd/framecast-kiosk.service`, change:
```ini
Requires=framecast.service
```
to:
```ini
BindsTo=framecast.service
```

**Step 2: Commit**
```bash
git add systemd/framecast-kiosk.service
git commit -m "fix: BindsTo instead of Requires — kiosk restarts when gunicorn dies"
```

---

### Task 1.3: Remove Persistent=true from per-minute schedule timer

**Files:**
- Modify: `systemd/framecast-schedule.timer`

`Persistent=true` on `OnCalendar=*:*:00` replays all missed invocations on boot. After 8 hours off, this fires 480 iterations of `hdmi-control.sh` immediately, hammering CEC and SD card.

**Step 1: Remove Persistent**

In `systemd/framecast-schedule.timer`, change:
```ini
[Timer]
OnCalendar=*:*:00
Persistent=true
```
to:
```ini
[Timer]
OnCalendar=*:*:00
AccuracySec=30
```

**Step 2: Commit**
```bash
git add systemd/framecast-schedule.timer
git commit -m "fix: remove Persistent=true from schedule timer — prevents boot storm"
```

---

### Task 1.4: Add time-sync and local-fs dependencies

**Files:**
- Modify: `systemd/framecast.service`
- Modify: `systemd/framecast-kiosk.service`

Pi has no RTC — clock starts at epoch until NTP syncs. "On This Day" EXIF matching breaks. Also missing `local-fs.target` for SD card readiness.

**Step 1: Fix framecast.service dependencies**

Change:
```ini
After=network-online.target
Wants=network-online.target
```
to:
```ini
After=network-online.target time-sync.target local-fs.target
Wants=network-online.target time-sync.target
```

**Step 2: Fix framecast-kiosk.service dependencies**

Add after existing `After=` line:
```ini
After=framecast.service graphical.target local-fs.target
```

**Step 3: Commit**
```bash
git add systemd/framecast.service systemd/framecast-kiosk.service
git commit -m "fix: add time-sync + local-fs dependencies — clock and filesystem ready before start"
```

---

### Task 1.5: Make EnvironmentFile non-fatal on schedule service

**Files:**
- Modify: `systemd/framecast-schedule.service`

If `.env` is missing (first boot before provisioning), the schedule service fails, and CEC schedule never runs.

**Step 1: Prefix with -**

Change:
```ini
EnvironmentFile=/opt/framecast/app/.env
```
to:
```ini
EnvironmentFile=-/opt/framecast/app/.env
```

**Step 2: Commit**
```bash
git add systemd/framecast-schedule.service
git commit -m "fix: non-fatal EnvironmentFile on schedule service — works without .env"
```

---

## Batch 2: HDMI Schedule Fixes (shell)

The HDMI display schedule is broken for overnight ranges and ignores the day-of-week setting entirely.

### Task 2.1: Fix overnight schedule wrap-around + add day-of-week check

**Files:**
- Modify: `scripts/hdmi-control.sh`

If ON_TIME=20:00 and OFF_TIME=06:00 (evening display), `ON_M > OFF_M` makes the condition always false. Also, `DISPLAY_SCHEDULE_DAYS` is completely ignored.

**Step 1: Rewrite check-schedule case**

Replace the entire `check-schedule)` block (lines 52-63) with:

```bash
  check-schedule)
    # Read schedule settings from environment (set by EnvironmentFile in service)
    SCHEDULE_ENABLED="${HDMI_SCHEDULE_ENABLED:-no}"
    if [[ "$SCHEDULE_ENABLED" != "yes" ]]; then
      exit 0
    fi

    # Day-of-week check (0=Sunday, 6=Saturday)
    SCHEDULE_DAYS="${DISPLAY_SCHEDULE_DAYS:-0,1,2,3,4,5,6}"
    TODAY_DOW=$(date +%w)
    if [[ ",$SCHEDULE_DAYS," != *",$TODAY_DOW,"* ]]; then
      exit 0  # Not a scheduled day
    fi

    ON_TIME="${HDMI_ON_TIME:-08:00}"
    OFF_TIME="${HDMI_OFF_TIME:-22:00}"
    to_minutes() { IFS=: read -r h m <<< "$1"; echo $(( 10#$h * 60 + 10#$m )); }
    NOW_M=$(to_minutes "$(date +%H:%M)")
    ON_M=$(to_minutes "$ON_TIME")
    OFF_M=$(to_minutes "$OFF_TIME")

    # Handle overnight ranges (e.g., ON=20:00, OFF=06:00)
    if [[ $ON_M -le $OFF_M ]]; then
      # Normal range (e.g., 08:00-22:00)
      [[ $NOW_M -ge $ON_M && $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
    else
      # Overnight range (e.g., 20:00-06:00)
      [[ $NOW_M -ge $ON_M || $NOW_M -lt $OFF_M ]] && "$0" on || "$0" off
    fi
    ;;
```

**Step 2: Move wlr-randr detection into on/off cases only**

Move the `HDMI_OUTPUT` detection (line 15) from the top of the script into only the `on)` and `off)` cases, since `check-schedule` calls `$0 on` or `$0 off` recursively anyway. This avoids 1,440 unnecessary wlr-randr calls/day.

Replace line 15:
```bash
# Remove from top level:
# HDMI_OUTPUT=$(wlr-randr 2>/dev/null | grep -Eo 'HDMI-[^ ]+' | head -1 || true)
# HDMI_OUTPUT="${HDMI_OUTPUT:-HDMI-A-1}"
```

Add to the top of the `on)` and `off)` cases:
```bash
  on)
    HDMI_OUTPUT=$(wlr-randr 2>/dev/null | grep -Eo 'HDMI-[^ ]+' | head -1 || true)
    HDMI_OUTPUT="${HDMI_OUTPUT:-HDMI-A-1}"
    # ... existing CEC logic ...
```

**Step 3: Commit**
```bash
git add scripts/hdmi-control.sh
git commit -m "fix: HDMI schedule — overnight wrap-around, day-of-week check, lazy wlr-randr"
```

---

## Batch 3: Kiosk Resilience (shell)

### Task 3.1: Fix kiosk.sh — curl timeout + configurable port

**Files:**
- Modify: `kiosk/kiosk.sh`

Curl has no `--max-time` (blocks forever if Flask hangs). Port 8080 is hardcoded (ignores `.env` WEB_PORT).

**Step 1: Rewrite kiosk.sh**

```bash
#!/usr/bin/env bash
# kiosk.sh — Wait for Flask, then launch cage with the GJS kiosk browser.
# Called by framecast-kiosk.service.
set -euo pipefail

# Read port from .env if available
ENV_FILE="/opt/framecast/app/.env"
WEB_PORT=8080
if [ -f "$ENV_FILE" ]; then
    WEB_PORT=$(grep "^WEB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8080")
    WEB_PORT="${WEB_PORT:-8080}"
fi

FLASK_URL="http://localhost:${WEB_PORT}/api/status"
MAX_WAIT=30

echo "FrameCast kiosk: waiting for Flask on port ${WEB_PORT} (up to ${MAX_WAIT}s)..."

ready=0
for i in $(seq 1 "$MAX_WAIT"); do
    if curl -sf --max-time 2 "$FLASK_URL" >/dev/null 2>&1; then
        ready=1
        echo "FrameCast kiosk: Flask ready after ${i}s"
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "FrameCast kiosk: ERROR — Flask did not respond within ${MAX_WAIT}s" >&2
    exit 1
fi

# Launch cage (Wayland kiosk compositor) with the GJS browser
exec cage -- gjs /opt/framecast/kiosk/browser.js
```

**Step 2: Commit**
```bash
git add kiosk/kiosk.sh
git commit -m "fix: kiosk.sh — curl timeout, configurable port from .env, env bash shebang"
```

---

## Batch 4: WiFi Manager Fix

### Task 4.1: Create missing wifi-check.sh script

**Files:**
- Create: `scripts/wifi-check.sh`

`wifi-manager.service` references this script but it doesn't exist. The script should check WiFi connectivity and start AP mode if disconnected, matching the architecture described in `wifi.py`.

**Step 1: Create the script**

```bash
#!/usr/bin/env bash
# wifi-check.sh — Check WiFi connectivity, start AP if disconnected.
# Called by wifi-manager.service on boot.
set -euo pipefail

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): WIFI: $*"; }

# Wait for NetworkManager to be ready
MAX_WAIT=30
for i in $(seq 1 "$MAX_WAIT"); do
    if nmcli general status >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Check if already connected
if nmcli -t -f GENERAL.STATE dev show wlan0 2>/dev/null | grep -qi "connected" && \
   ! nmcli -t -f GENERAL.STATE dev show wlan0 2>/dev/null | grep -qi "disconnected"; then
    SSID=$(nmcli -t -f GENERAL.CONNECTION dev show wlan0 2>/dev/null | cut -d: -f2 || true)
    log "Connected to ${SSID:-unknown}"
    exit 0
fi

# Try known networks first
log "Not connected — attempting known networks"
if nmcli dev wifi connect 2>/dev/null; then
    log "Connected via known network"
    exit 0
fi

log "No known networks available — AP mode will be started by the web app on first request"
exit 0
```

**Step 2: Make executable**

Run: `chmod +x scripts/wifi-check.sh`

**Step 3: Commit**
```bash
git add scripts/wifi-check.sh
git commit -m "fix: create missing wifi-check.sh referenced by wifi-manager.service"
```

---

## Batch 5: Database Lifecycle (Python)

### Task 5.1: Add WAL checkpoint on clean shutdown

**Files:**
- Modify: `app/modules/db.py`
- Test: `tests/test_db.py`

The atexit handler only flushes stats. WAL file grows indefinitely without a clean shutdown checkpoint.

**Step 1: Write failing test**

In `tests/test_db.py`, add:
```python
def test_shutdown_db_checkpoints_wal(initialized_db, monkeypatch):
    """Clean shutdown should checkpoint WAL."""
    db_mod = initialized_db
    checkpointed = []
    original_get_db = db_mod.get_db

    def tracking_get_db():
        conn = original_get_db()
        original_execute = conn.execute
        def tracking_execute(sql, *args, **kwargs):
            if "wal_checkpoint" in str(sql).lower():
                checkpointed.append(sql)
            return original_execute(sql, *args, **kwargs)
        conn.execute = tracking_execute
        return conn

    monkeypatch.setattr(db_mod, "get_db", tracking_get_db)
    db_mod._shutdown_db()
    assert len(checkpointed) > 0, "WAL checkpoint should run on shutdown"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db.py::test_shutdown_db_checkpoints_wal -v`
Expected: FAIL — `_shutdown_db` does not exist

**Step 3: Implement _shutdown_db and wire to atexit**

In `app/modules/db.py`, add after `_flush_stats`:
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
```

In `init_db()`, change:
```python
atexit.register(_flush_stats)
```
to:
```python
atexit.register(_shutdown_db)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db.py::test_shutdown_db_checkpoints_wal -v`
Expected: PASS

**Step 5: Commit**
```bash
git add app/modules/db.py tests/test_db.py
git commit -m "fix: WAL checkpoint on clean shutdown — prevents WAL growth on SD card"
```

---

### Task 5.2: Guard init_db against double registration

**Files:**
- Modify: `app/modules/db.py`

`init_db()` registers atexit and starts timer threads every time it's called. Multiple calls = multiple timers = wasted resources.

**Step 1: Add module-level guard**

At the top of `db.py`, near other module globals:
```python
_db_initialized = False
```

In `init_db()`, wrap the atexit/timer section:
```python
    global _db_initialized
    if not _db_initialized:
        # Auto-prune old display stats on startup
        _prune_old_stats()

        # Register atexit handler for stats buffer flush
        atexit.register(_shutdown_db)

        # Start periodic flush timer
        _start_flush_timer()

        _db_initialized = True

    log.info("DATABASE: INITIALIZED at %s", db_path)
```

**Step 2: Commit**
```bash
git add app/modules/db.py
git commit -m "fix: guard init_db against double atexit/timer registration"
```

---

### Task 5.3: Fix migrate_from_files bare connection

**Files:**
- Modify: `app/modules/db.py`

The standalone path (`conn=None`) opens a raw connection without `contextlib.closing()`, violating the project convention (Lesson #34).

**Step 1: Fix the own_conn path**

In `migrate_from_files()`, change:
```python
    own_conn = conn is None
    if own_conn:
        conn = get_db()

    try:
        # ... body ...
    finally:
        if own_conn:
            conn.close()
```
to:
```python
    if conn is None:
        with closing(get_db()) as own_conn:
            _do_migrate(own_conn, media_dir)
        return
    _do_migrate(conn, media_dir)
```

Extract the body into `_do_migrate(conn, media_dir)` — a private function that receives an already-open connection. This eliminates the manual `try/finally` pattern entirely.

**Step 2: Run existing tests**

Run: `python3 -m pytest tests/test_db.py -v --timeout=120`
Expected: All pass

**Step 3: Commit**
```bash
git add app/modules/db.py
git commit -m "fix: migrate_from_files uses closing() for standalone connection (Lesson #34)"
```

---

### Task 5.4: Cache ephemeral FLASK_SECRET_KEY

**Files:**
- Modify: `app/modules/auth.py`

When `FLASK_SECRET_KEY` is empty, a new random key is generated per call to `_make_auth_token()`. This means the cookie set during `verify_pin` will never match the check in `require_pin` — auth is completely broken.

**Step 1: Add module-level cache**

At the top of `auth.py`, after the existing imports:
```python
_ephemeral_secret = None
```

In `_make_auth_token()`, change:
```python
    secret = config.get("FLASK_SECRET_KEY", "")
    if not secret:
        log.error("FLASK_SECRET_KEY not set — auth tokens will be insecure")
        # Generate ephemeral key for this session (forces PIN re-entry on restart)
        import secrets as _secrets
        secret = _secrets.token_hex(24)
```
to:
```python
    global _ephemeral_secret
    secret = config.get("FLASK_SECRET_KEY", "")
    if not secret:
        if _ephemeral_secret is None:
            _ephemeral_secret = secrets.token_hex(24)
            log.error("FLASK_SECRET_KEY not set — using ephemeral key (auth invalidated on restart)")
        secret = _ephemeral_secret
```

Remove the `import secrets as _secrets` inside the function — `secrets` is already imported at the module level (line 23).

**Step 2: Run existing tests**

Run: `python3 -m pytest tests/test_auth.py -v --timeout=120`
Expected: All pass

**Step 3: Commit**
```bash
git add app/modules/auth.py
git commit -m "fix: cache ephemeral FLASK_SECRET_KEY — auth works without .env key"
```

---

## Batch 6: Error Handling (Python)

### Task 6.1: BaseException → Exception in atomic write helpers

**Files:**
- Modify: `app/modules/config.py`
- Modify: `app/modules/updater.py`

`BaseException` catches `SystemExit` and `KeyboardInterrupt`, which delays graceful shutdown.

**Step 1: Fix config.py**

In `app/modules/config.py`, line 85, change:
```python
        except BaseException:
```
to:
```python
        except Exception:
```

**Step 2: Fix updater.py**

In `app/modules/updater.py`, line 135, same change:
```python
        except BaseException:
```
to:
```python
        except Exception:
```

**Step 3: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=120 -x`
Expected: All pass

**Step 4: Commit**
```bash
git add app/modules/config.py app/modules/updater.py
git commit -m "fix: BaseException → Exception in atomic writes — unblock graceful shutdown"
```

---

### Task 6.2: Add lock to thumbnail cleanup

**Files:**
- Modify: `app/web_upload.py`

With `gthread` (2 threads), two concurrent requests can race on `_thumbnail_cleanup_last`, running cleanup simultaneously.

**Step 1: Add lock**

Near `_thumbnail_cleanup_last` (around line 794), add:
```python
_thumbnail_cleanup_lock = threading.Lock()
```

Replace the `_periodic_thumbnail_cleanup` function:
```python
@app.before_request
def _periodic_thumbnail_cleanup():
    """Run orphan thumbnail cleanup hourly, triggered by any request."""
    global _thumbnail_cleanup_last
    if not _thumbnail_cleanup_lock.acquire(blocking=False):
        return  # Another thread is already cleaning
    try:
        now = time.monotonic()
        if now - _thumbnail_cleanup_last > _THUMBNAIL_CLEANUP_INTERVAL:
            _thumbnail_cleanup_last = now
            try:
                removed = media.cleanup_orphan_thumbnails()
                if removed:
                    log.info("Cleaned up %d orphan thumbnail(s)", removed)
            except Exception:
                log.warning("Periodic thumbnail cleanup failed", exc_info=True)
    finally:
        _thumbnail_cleanup_lock.release()
```

**Step 2: Commit**
```bash
git add app/web_upload.py
git commit -m "fix: add lock to thumbnail cleanup — prevent race with gthread workers"
```

---

### Task 6.3: Protect file unlink in delete route

**Files:**
- Modify: `app/web_upload.py`

The delete route updates the DB (quarantines photo) then calls `unlink()` with no error handling. If unlink fails, the DB says "deleted" but the file remains.

**Step 1: Wrap unlinks in try/except**

Find the delete route's unlink section (around lines 596-600). Replace:
```python
        # Remove associated thumbnail if it exists
        thumb_path = Path(THUMBNAIL_DIR) / (filepath.stem + ".jpg")
        if thumb_path.exists():
            thumb_path.unlink()
        filepath.unlink()
```
with:
```python
        # Remove associated thumbnail if it exists
        thumb_path = Path(THUMBNAIL_DIR) / (filepath.stem + ".jpg")
        try:
            if thumb_path.exists():
                thumb_path.unlink()
        except OSError as exc:
            log.warning("Failed to remove thumbnail for %s: %s", filepath.name, exc)

        try:
            filepath.unlink()
        except OSError as exc:
            log.error("Failed to delete file %s: %s — un-quarantining in DB", filepath.name, exc)
            if photo_row:
                db.update_photo_quarantine(photo_row["id"], False, None)
            if xhr:
                return jsonify({"error": "File deletion failed"}), 500
            flash("File deletion failed", "error")
            return redirect(url_for("index"))
```

**Step 2: Commit**
```bash
git add app/web_upload.py
git commit -m "fix: protect file unlink in delete route — un-quarantine on failure"
```

---

### Task 6.4: Abort delete-all on DB failure

**Files:**
- Modify: `app/web_upload.py`

The `delete_all` route catches the DB bulk-quarantine failure but then proceeds to delete all files, creating orphan DB records.

**Step 1: Abort on DB failure**

Find the `delete_all` function's DB exception handler (around line 637). Change:
```python
    except Exception as db_exc:
        log.error("Failed to bulk-quarantine photos in DB: %s", db_exc)
```
to:
```python
    except Exception as db_exc:
        log.error("Failed to bulk-quarantine photos in DB: %s", db_exc)
        flash("Delete all failed: database error. Try rebooting.", "error")
        return redirect(url_for("index"))
```

**Step 2: Also wrap individual unlinks in the loop**

Replace the file deletion loop:
```python
    count = 0
    for f in media_path.iterdir():
        if f.is_file() and f.suffix.lower() in all_ext:
            f.unlink()
            count += 1
```
with:
```python
    count = 0
    for f in media_path.iterdir():
        if f.is_file() and f.suffix.lower() in all_ext:
            try:
                f.unlink()
                count += 1
            except OSError as exc:
                log.warning("Failed to delete %s during delete-all: %s", f.name, exc)
```

**Step 3: Commit**
```bash
git add app/web_upload.py
git commit -m "fix: abort delete-all on DB failure + protect individual unlinks"
```

---

## Batch 7: Security Tightening

### Task 7.1: Remove unpkg.com from CSP

**Files:**
- Modify: `app/web_upload.py`

Leaflet CSS is bundled locally (PR #79), but the CSP still allows scripts and styles from `unpkg.com`. This is a supply chain attack surface.

**Step 1: Remove unpkg.com from CSP**

Find the `security_headers` function (around line 244). Change:
```python
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "media-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com"
    )
```
to:
```python
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
        "media-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
```

**Step 2: Verify Leaflet CSS is bundled**

Run: `ls app/static/css/leaflet.css`
Expected: File exists (bundled by PR #79)

**Step 3: Commit**
```bash
git add app/web_upload.py
git commit -m "security: remove unpkg.com from CSP — all assets bundled locally"
```

---

## Batch 8: Health Check Hardening (shell)

### Task 8.1: Replace sleep 10 with curl readiness loop

**Files:**
- Modify: `scripts/health-check.sh`

The health check uses `sleep 10` before checking services. On a slow Pi 3B with SD card, gunicorn may need 15-30s to become ready. A good update gets incorrectly rolled back.

**Step 1: Replace sleep with curl loop**

Replace line 69 (`sleep 10`) and the service check loop (lines 72-78) with:

```bash
# Wait for Flask to be ready (not just systemd active)
WEB_PORT=8080
if [ -f "$ENV_FILE" ]; then
    WEB_PORT=$(grep "^WEB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8080")
    WEB_PORT="${WEB_PORT:-8080}"
fi

echo "Waiting for Flask readiness on port ${WEB_PORT}..."
HEALTHY=false
for i in $(seq 1 30); do
    if curl -sf --max-time 2 "http://localhost:${WEB_PORT}/api/status" >/dev/null 2>&1; then
        HEALTHY=true
        echo "Flask ready after ${i}s"
        break
    fi
    sleep 2
done

# Also verify kiosk service is active
if [ "$HEALTHY" = "true" ]; then
    if ! systemctl is-active --quiet framecast-kiosk; then
        echo "WARN: Flask is ready but kiosk is not active"
        # Give kiosk a bit more time (it waits for Flask first)
        sleep 10
        if ! systemctl is-active --quiet framecast-kiosk; then
            echo "FAIL: framecast-kiosk is not active"
            HEALTHY=false
        fi
    fi
fi
```

**Step 2: Commit**
```bash
git add scripts/health-check.sh
git commit -m "fix: health check uses curl readiness loop — prevents rolling back good updates"
```

---

### Task 8.2: Clean up rollback files in EXIT trap

**Files:**
- Modify: `scripts/health-check.sh`

If both `git checkout` attempts fail (lines 88-93), the rollback files are never cleaned up. On next boot, health-check tries the same broken rollback in an infinite loop.

**Step 1: Add EXIT trap at the top of the script**

After the `set -euo pipefail` line, add:
```bash
cleanup_rollback_files() {
    rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"
}
```

Then, after the HMAC validation succeeds (line 52), add:
```bash
# Ensure rollback files are always cleaned up, even on script failure
trap cleanup_rollback_files EXIT
```

**Step 2: Remove the inline rm -f calls**

Remove these lines since the trap handles cleanup:
- Line 82: `rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"` (after health pass)
- Line 96: `rm -f "$ROLLBACK_FILE" "$ROLLBACK_SIG"` (before reboot)

Keep the early-exit cleanup calls (lines 23, 30, 42) since they fire before the trap is installed.

**Step 3: Commit**
```bash
git add scripts/health-check.sh
git commit -m "fix: EXIT trap cleans rollback files — prevents infinite rollback loop"
```

---

## Summary

| Batch | Focus | Tasks | Impact |
|-------|-------|-------|--------|
| 1 | Brick prevention (systemd) | 5 | Eliminates permanent device lockout |
| 2 | HDMI schedule (shell) | 1 | Fixes overnight + day-of-week schedule |
| 3 | Kiosk resilience (shell) | 1 | Prevents kiosk boot failure on slow/custom systems |
| 4 | WiFi manager (shell) | 1 | Creates missing boot script |
| 5 | Database lifecycle (Python) | 4 | WAL checkpoint, init guard, connection safety, auth fix |
| 6 | Error handling (Python) | 4 | Prevents silent data loss on delete operations |
| 7 | Security (Python) | 1 | Removes supply chain attack surface |
| 8 | Health check (shell) | 2 | Prevents rolling back good updates |

**Total: 19 tasks across 8 batches**

Batches 1-3 are the highest priority — they eliminate the "permanent brick" failure modes that require physical access to fix. Batches 4-8 harden against silent failures and data loss.
