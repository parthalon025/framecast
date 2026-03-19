# FrameCast v2 Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Polish FrameCast v2 from prototype to production-ready: reliability fixes, SQLite content model, smart slideshow, favorites/albums, multi-user, HDMI-CEC, security hardening, and documentation.

**Architecture:** Two sequential foundation PRs (reliability + SQLite), then 6 parallel feature PRs in isolated worktrees. All frontend follows superhot-ui green phosphor design system. SQLite DB for content metadata. Pi 3 (1GB RAM) as hardware floor.

**Tech Stack:** Python/Flask, SQLite3, Preact/esbuild, superhot-ui, systemd, pi-gen, cec-utils, ufw

**Design Doc:** `docs/plans/2026-03-19-framecast-v2-polish-design.md`

---

## Pre-Execution

### Step 0: Merge PR #11 (v2 foundation)

```bash
cd /home/justin/Documents/projects/framecast
gh pr merge 11 --squash --delete-branch
git checkout main && git pull
```

### Step 0.1: Merge design doc PR

```bash
gh pr create --title "docs: v2 polish design" --body "Gap analysis + 8-phase improvement plan with superhot-ui rules" --base main --head docs/v2-polish-design
gh pr merge --squash --delete-branch
git checkout main && git pull
```

### Step 0.2: Create PRDs for major features

Run `/create-prd` for each:
1. **Content System** — favorites, albums, tags, smart albums (Agent 3)
2. **Smart Slideshow** — weighted rotation, "on this day", transition randomization (Agent 1)
3. **Multi-User + Stats** — user tracking, stats dashboard (Agent 4)

PRDs go to `tasks/prd-<slug>.json` with shell-verifiable acceptance criteria.

---

## Batch 1: Phase 1A — Reliability Fixes (Sequential)

**Branch:** `fix/reliability`

### Task 1.1: Gunicorn Hardening

**Files:**
- Modify: `app/gunicorn.conf.py` (42 lines)

**Step 1: Enforce single worker + fix graceful timeout**

```python
# gunicorn.conf.py — replace entire file
import os
import multiprocessing

# MANDATORY: FrameCast requires 1 worker (SSE, CEC, stats buffer are process-singletons)
# Lesson #1356: gthread workers fork singletons — each gets its own SSE broadcaster
_requested = os.environ.get("GUNICORN_WORKERS", "1")
if _requested != "1":
    raise SystemExit("ERROR: FrameCast requires workers=1 (SSE/CEC/stats are process-singletons)")
workers = 1

# gthread: threads handle I/O concurrency within the single worker
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# Timeouts
timeout = 120          # max request duration (large uploads)
graceful_timeout = 120 # match request timeout — don't kill uploads on restart
keepalive = 5

# Binding
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Logging
loglevel = os.environ.get("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"
```

**Step 2: Commit**

```bash
git add app/gunicorn.conf.py
git commit -m "fix: enforce single gunicorn worker, match graceful timeout to request timeout"
```

### Task 1.2: Systemd Service Hardening

**Files:**
- Modify: `systemd/framecast.service`
- Modify: `systemd/framecast-kiosk.service`
- Modify: `systemd/wifi-manager.service`
- Modify: `systemd/framecast-update.service`

**Step 1: Harden all service files**

`framecast.service`:
```ini
[Unit]
Description=FrameCast Web Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/framecast/app
ExecStart=/usr/bin/gunicorn -c gunicorn.conf.py web_upload:app
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
WatchdogSec=120
MemoryMax=512M
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=/opt/framecast /var/lib/framecast
StandardOutput=journal
StandardError=journal
SyslogIdentifier=framecast

[Install]
WantedBy=multi-user.target
```

`framecast-kiosk.service`:
```ini
[Unit]
Description=FrameCast Kiosk Display
After=graphical.target
Requires=framecast.service

[Service]
Type=simple
User=pi
ExecStart=/opt/framecast/kiosk/kiosk.sh
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=5
WatchdogSec=60
MemoryMax=512M
Environment=DISPLAY=:0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=framecast-kiosk

[Install]
WantedBy=graphical.target
```

**Step 2: Commit**

```bash
git add systemd/
git commit -m "fix: harden systemd services — start limits, watchdog, security directives"
```

### Task 1.3: SSE Robustness

**Files:**
- Modify: `app/sse.py` (98 lines)

**Step 1: Add heartbeat, backoff support, cold-start replay, broken pipe handling**

Replace `app/sse.py` with improved version adding:
- Configurable heartbeat (20s default)
- `last-event-id` tracking for reconnection
- Event coalescing (2s debounce window for rapid events)
- Send `state:current` as first event on connect (Lesson #604)
- Catch BrokenPipeError + GeneratorExit (Lesson #36)
- Event ID counter for gap detection

**Step 2: Update frontend SSE consumers** — add exponential backoff in `Slideshow.jsx` and `Upload.jsx`:
- Reconnect: 1s → 2s → 4s → 8s, cap 60s
- Reset backoff on successful connection

**Step 3: Commit**

```bash
git add app/sse.py app/frontend/src/display/Slideshow.jsx app/frontend/src/pages/Upload.jsx
git commit -m "fix: SSE robustness — heartbeat, backoff, cold-start replay, broken pipe handling"
```

### Task 1.4: Corrupt Image Handling

**Files:**
- Modify: `app/web_upload.py:281-315` (_auto_resize_image)
- Modify: `app/web_upload.py:365-456` (_do_upload)
- Modify: `app/modules/media.py:60-90` (get_media_files)
- Modify: `app/frontend/src/display/Slideshow.jsx:103-126` (setLayerContent)

**Step 1: Wrap Pillow operations in try/except + timeout**

In `_do_upload`: after file save, validate image with `PILImage.open().verify()`. On failure, move to `quarantine/` subdir with reason logged. Add 30s SIGALRM timeout around Pillow operations.

In `Slideshow.jsx:setLayerContent`: add `onerror` handler on `<img>` that triggers advance to next photo after 3s.

**Step 2: Commit**

```bash
git add app/web_upload.py app/modules/media.py app/frontend/src/display/Slideshow.jsx
git commit -m "fix: quarantine corrupt images, skip broken photos in slideshow"
```

### Task 1.5: Health-Check Rollback Wiring

**Files:**
- Modify: `scripts/health-check.sh` (61 lines)
- Modify: `app/modules/updater.py:94-127` (apply_update)
- Create: `systemd/framecast-health.service`
- Create: `systemd/framecast-health.timer`

**Step 1: Move rollback tag to /var/lib/framecast/ with HMAC**

In `updater.py`: write rollback tag + HMAC to `/var/lib/framecast/rollback-tag` and `/var/lib/framecast/rollback-sig`. Use FLASK_SECRET_KEY for HMAC.

In `health-check.sh`: validate HMAC before trusting rollback tag. Check tag exists in git.

**Step 2: Create systemd timer**

`framecast-health.timer` — runs 90s after boot.

**Step 3: Commit**

```bash
git add scripts/health-check.sh app/modules/updater.py systemd/framecast-health.*
git commit -m "fix: wire health-check rollback to systemd, HMAC-sign rollback tag"
```

### Task 1.6: WiFi AP Auto-Timeout

**Files:**
- Modify: `app/modules/wifi.py:142-175` (start_ap)

**Step 1: Add 30-minute timeout + logging**

Add `_ap_start_time` tracking. In a background thread, check after 30 minutes — if no client connected, restart AP. Log all AP state transitions (started, client connected, timeout, stopped).

**Step 2: Commit**

```bash
git add app/modules/wifi.py
git commit -m "fix: auto-timeout WiFi AP after 30 minutes of no connections"
```

### Task 1.7: GPS Cache Fsync

**Files:**
- Modify: `app/modules/media.py:220-246` (_save_locations_cache)

**Step 1: Add fsync before replace**

Add `f.flush(); os.fsync(f.fileno())` before `Path(tmp_path).replace(cache_path)` — match the pattern in `config.py:80`.

**Step 2: Commit**

```bash
git add app/modules/media.py
git commit -m "fix: fsync GPS cache before replace (match config.py pattern)"
```

### Task 1.8: Image Processing Timeout

**Files:**
- Modify: `app/web_upload.py:281-315` (_auto_resize_image)

**Step 1: Add SIGALRM timeout**

Reuse existing `request_timeout` decorator pattern (lines 162-189). Wrap `_auto_resize_image` body with 30s alarm.

**Step 2: Commit**

```bash
git add app/web_upload.py
git commit -m "fix: 30s timeout on Pillow image processing operations"
```

### Task 1.9: Smoke Test Fix

**Files:**
- Modify: `scripts/smoke-test.sh` (345 lines — full rewrite)

**Step 1: Rewrite for v2**

Replace all v1 references:
- Paths: `/opt/pi-photo-display` → `/opt/framecast`
- Services: `slideshow`, `photo-upload` → `framecast`, `framecast-kiosk`
- Remove VLC checks (lines 214-226)
- Add: frontend asset check (`app/static/js/` + `app/static/css/`)
- Add: Python syntax check (`python3 -m py_compile app/*.py app/modules/*.py`)
- Add: systemd unit validation (`systemd-analyze verify`)
- Clean exit codes: 0=pass, 1=warnings, 2=critical

**Step 2: Commit**

```bash
git add scripts/smoke-test.sh
git commit -m "fix: rewrite smoke-test.sh for v2 — correct paths, services, add build checks"
```

### Task 1.10: Create PR for Phase 1A

```bash
gh pr create --title "fix: Phase 1A reliability — watchdog, rollback, SSE, corrupt images" \
  --body "10 reliability fixes from gap analysis. See docs/plans/2026-03-19-framecast-v2-polish-design.md" \
  --base main
```

---

## Batch 2: Phase 1B — SQLite Schema + Migration (Sequential)

**Branch:** `feature/sqlite-content-model`
**Depends on:** Batch 1 merged

### Task 2.1: Create db.py Module

**Files:**
- Create: `app/modules/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest, tempfile, os
from pathlib import Path

def test_init_creates_tables():
    with tempfile.TemporaryDirectory() as d:
        os.environ["MEDIA_DIR"] = d
        from app.modules import db
        db.init_db()
        conn = db.get_db()
        with conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "photos" in tables
        assert "albums" in tables
        assert "schema_version" in tables

def test_wal_mode_enabled():
    with tempfile.TemporaryDirectory() as d:
        os.environ["MEDIA_DIR"] = d
        from app.modules import db
        db.init_db()
        conn = db.get_db()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

def test_duplicate_detection():
    # ... test SHA256 dedup returns 409
```

**Step 2: Implement db.py**

Full schema from design doc. Key patterns:
- `contextlib.closing()` on all connections (Lesson #34)
- WAL mode + busy_timeout=5000 (Lesson #1335)
- Write lock via threading.Lock
- Atomic toggle: `UPDATE SET x = NOT x` (Lesson #1274)

**Step 3: Run tests, commit**

```bash
pytest tests/test_db.py -v
git add app/modules/db.py tests/test_db.py
git commit -m "feat: add SQLite content model with photos, albums, tags, users, stats"
```

### Task 2.2: Migration from File-Based to DB

**Files:**
- Modify: `app/modules/db.py` (add migration functions)
- Create: `tests/test_migration.py`

**Step 1: Implement migration**

`migrate_from_files()`:
1. Scan MEDIA_DIR (skip quarantine/, thumbnails/)
2. For each file: SHA256, EXIF, GPS, INSERT into photos
3. Import GPS JSON cache
4. Delete old cache
5. Set schema_version = 1

Order: INSERT (quarantined=1) → file already exists → UPDATE quarantined=0 (Lesson #1670).

**Step 2: Tests + commit**

### Task 2.3: Wire DB into Flask Routes

**Files:**
- Modify: `app/web_upload.py` (upload, delete, photos list, locations)

Replace file-system scanning with DB queries. Add new endpoints:
- `GET /api/photos` — paginated, filterable
- `GET /api/photos/<id>/favorite` — toggle
- `GET /api/albums`, `POST /api/albums`
- `GET /api/tags`, `POST /api/photos/<id>/tags`
- `GET /api/stats`
- `GET /api/users`
- `GET /api/backup`

Upload order: validate → INSERT (quarantined=1) → write file → fsync → UPDATE quarantined=0.

**Step 3: Commit**

### Task 2.4: Display Stats Buffering

**Files:**
- Add to: `app/modules/db.py`

Buffer stats in memory, flush every 5 minutes:
```python
_stats_buffer = []
_stats_lock = threading.Lock()

def record_view(photo_id, duration, transition):
    with _stats_lock:
        _stats_buffer.append((photo_id, duration, transition, _now()))
        if len(_stats_buffer) >= 30:
            _flush_stats()

def _flush_stats():
    # bulk INSERT, single write — reduces SD writes 50x
```

### Task 2.5: Extract PhotoCard Component

**Files:**
- Create: `app/frontend/src/components/PhotoCard.jsx`
- Modify: `app/frontend/src/pages/Upload.jsx` (import PhotoCard)

Extract the photo card markup from Upload.jsx's inline `.map()` into a standalone component. Pure refactor — no new features.

```jsx
// PhotoCard.jsx
export function PhotoCard({ photo, onDelete }) {
  // ... existing card markup from Upload.jsx
}
```

### Task 2.6: Tests + PR

```bash
pytest tests/ -v
npm run build  # verify frontend builds
git add -A && git commit -m "feat: SQLite content model, migration, PhotoCard extraction"
gh pr create --title "feat: Phase 1B — SQLite content model + migration" \
  --body "SQLite schema, file→DB migration, API rewire, PhotoCard extraction"
```

---

## Batch 3-8: Phase 2 — Parallel Agents (6 Worktrees)

**Depends on:** Batch 2 merged
**Execution:** All 6 agents launch simultaneously in isolated worktrees.

### Pre-Launch: Create PRDs

Before launching agents, create PRDs for the three feature PRs:

```bash
# Run /create-prd for each major feature
/create-prd "Smart Slideshow — weighted rotation, on-this-day, transition randomization"
/create-prd "Content System — favorites, albums, tags, smart albums, lightbox"
/create-prd "Multi-User + Stats — user tracking, view counts, stats dashboard"
```

### Agent Dispatch

```
Agent 1 → .worktrees/smart-slideshow/     → feature/smart-slideshow
Agent 2 → .worktrees/settings-ux/          → feature/settings-ux
Agent 3 → .worktrees/favorites-albums/     → feature/favorites-albums
Agent 4 → .worktrees/multi-user-stats/     → feature/multi-user-stats
Agent 5 → .worktrees/hdmi-cec/             → feature/hdmi-cec
Agent 6 → .worktrees/security-docs/        → feature/security-docs
```

---

### Batch 3: Agent 1 — Smart Slideshow

**Branch:** `feature/smart-slideshow`
**Owns:** `app/modules/rotation.py` (new), `app/frontend/src/display/Slideshow.jsx`, `app/frontend/src/app.css` (transition sections only)

**Tasks:**
1. Create `rotation.py` with weighted selection algorithm
2. Write `GET /api/slideshow/playlist` endpoint (50 photos, weighted)
3. Implement "On This Day" feature (EXIF date match)
4. Add transition randomization (setting: `TRANSITION_MODE = single|random`)
5. Improve Ken Burns (9 anchor points, aspect-aware, `will-change`)
6. Add video handling (skip transitions, codec error → quarantine)
7. Rewrite `Slideshow.jsx` to use playlist API instead of local shuffle
8. Unit tests for rotation.py (distribution, diversity, on-this-day)
9. Commit + PR

**superhot-ui rules:** `detectCapability()` at init for Pi 3 downgrade. No decorative idle animation. `prefers-reduced-motion` disables all transitions.

---

### Batch 4: Agent 2 — Settings & UX Polish

**Branch:** `feature/settings-ux`
**Owns:** `app/frontend/src/pages/Settings.jsx`, `Upload.jsx`, `Onboard.jsx`, `app/frontend/src/components/`, `app.css` (layout sections)

**Tasks:**
1. First-boot onboarding wizard (4 steps: Welcome → WiFi → Upload → Done)
   - Use `.sh-progress-steps` for step indicators
   - TV shows QR code + plain text throughout
   - `ONBOARDING_COMPLETE` config flag
2. Complete Settings page:
   - Display: transition mode/duration/Ken Burns (`.sh-select`, `.sh-input`)
   - Security: PIN change/regenerate (`.sh-input`)
   - Schedule: on/off times + days (`.sh-input[type=time]`)
   - Network: SSID, signal, IP (read-only, `.sh-label` + `.sh-value`)
   - System: storage bar (`.sh-threshold-bar`), version, restart button
   - Use `ShCollapsible` for each section
3. Batch upload progress ("UPLOADING 3/12", per-file indicators, retry)
4. Error states:
   - `fetch()` timeout (15s/60s)
   - Offline banner (`navigator.onLine` + SSE state)
   - Settings load: "RETRY" button (`.sh-clickable`)
   - Validation: `aria-invalid` per field
5. Accessibility:
   - Focus trap on PinGate + delete modals (ShModal has this built in)
   - `<main>`, `<nav>`, `<section>` landmarks
   - Signal bars: `aria-label`
   - Toast above nav bar
6. Tests + PR

**superhot-ui voice:** `STANDBY` not "Loading...", `FAULT` not "Error", `CONFIRM: DELETE?` not "Are you sure?". All forms use `.sh-input`, `.sh-select`, `.sh-toggle`. 24h time, ISO dates.

---

### Batch 5: Agent 3 — Favorites + Albums

**Branch:** `feature/favorites-albums`
**Owns:** `PhotoCard.jsx` (features), `Lightbox.jsx` (new), `Albums.jsx` (new), album/tag API routes

**Tasks:**
1. Add favorite toggle to PhotoCard (gold star, `POST /api/photos/{id}/favorite`)
2. Add selection mode to PhotoCard (checkboxes for bulk actions)
3. Create Lightbox component (full-screen, swipe, pinch-zoom, EXIF info)
4. Create Albums page:
   - Album grid with covers
   - Create/delete albums
   - Add photos to album (selection → add)
   - Use `.sh-filter-panel` + `.sh-filter-chip` for filtering
5. Implement Smart Albums (computed queries, `smart: true` flag):
   - "Recent" (last 30 days)
   - "On This Day" (EXIF date match)
   - "Most Shown" (top 20 by view_count)
6. Tags: chips in lightbox, auto-suggest, slideshow filter
7. Filter bar on Upload: "ALL | FAVORITES | HIDDEN" using `.sh-filter-chip`
8. DB query tests
9. Commit + PR

**superhot-ui:** Filter chips via `.sh-filter-chip--active`. Lightbox uses `.sh-modal-overlay` pattern. No emoji icons — text labels `[FAV]`, `[TAG]`, `[DELETE]`.

---

### Batch 6: Agent 4 — Multi-User + Stats

**Branch:** `feature/multi-user-stats`
**Owns:** `app/modules/users.py` (new), `Stats.jsx` (new), `Users.jsx` (new), user API routes

**Tasks:**
1. Create `users.py` module (CRUD, cookie tracking)
2. "Who's uploading?" prompt on first upload (user list + "NEW")
3. Cookie `framecast_user` (30 days)
4. Per-user filtering on Upload page
5. Stats dashboard page:
   - Total photos/videos/storage (`ShStatCard`)
   - Photos by user (`ShDataTable`)
   - Upload timeline (ASCII bar — `ShStatsGrid`)
   - Most shown / least shown (`ShDataTable`)
   - Use `formatTime()` for all timestamps
6. Empty-state handling (fresh DB → valid responses, `NO DATA`)
7. DB tests + PR

**superhot-ui:** Stats page layout: `ShStatsGrid` for metric cards, `ShDataTable` for lists (left-justified, no zebra). Opacity for historical data. `formatTime(ts, "relative")` for "3h 14m ago".

---

### Batch 7: Agent 5 — HDMI-CEC

**Branch:** `feature/hdmi-cec`
**Owns:** `app/modules/cec.py` (new), `scripts/hdmi-control.sh`, schedule systemd units

**Tasks:**
1. Create `cec.py` (tv_power_on, tv_standby, tv_status, set_active_source)
   - All via `cec-client` subprocess with 5s timeout
   - `suppress(ProcessLookupError)` on kill (Lesson #81)
   - Init queries state (Lesson #7 — don't assume)
2. Rewrite `hdmi-control.sh`:
   - CEC-first, `wlr-randr` fallback
   - Dynamic HDMI output detection
3. Create schedule systemd units:
   - `framecast-schedule.timer` (every minute)
   - `framecast-schedule.service` (check time vs settings)
4. Wire `DISPLAY_ON_TIME`/`DISPLAY_OFF_TIME`/`DISPLAY_SCHEDULE_DAYS` to CEC
5. Add `cec-utils` to pi-gen packages
6. Mock subprocess tests
7. Commit + PR

---

### Batch 8: Agent 6 — Security Hardening + Docs

**Branch:** `feature/security-docs`
**Owns:** `pi-gen/`, `scripts/smoke-test.sh` (if not done in 1A), `auth.py`, `updater.py`, docs

**Tasks:**
1. Firewall: add `ufw` to pi-gen, configure rules (8080/tcp RFC1918, mDNS)
2. Stronger PIN: `PIN_LENGTH` setting (4/6), tighter rate limits for 6-digit
3. Rollback tag hardening: `/var/lib/framecast/`, HMAC verification
4. Update signing: SHA256 pinning after git fetch
5. Additional security:
   - `SameSite=Strict` cookies + Origin validation
   - `python3-magic` for MIME validation
   - API rate limiting (60 req/min per IP)
6. Smoke test final polish (if tasks remain from 1A)
7. Documentation:
   - README.md: v2 features, setup guide, troubleshooting
   - CONTRIBUTING.md: architecture, dev setup, PR guidelines
   - API.md: all endpoints with request/response examples
8. Commit + PR

---

## Post-Merge: Comprehensive Review

After all 8 PRs are merged, run full review:

1. **Security review** — launch `security-reviewer` agent on full diff
2. **Silent failure hunt** — launch `silent-failure-hunter` agent
3. **Code review** — launch `coderabbit:code-reviewer` on combined changes
4. **Lesson scanner** — `lessons-db scan --target . --baseline v2.0.0`
5. **Smoke test** — run updated `scripts/smoke-test.sh`
6. **Frontend build** — `cd app/frontend && npm run build` (verify bundle)
7. **Test suite** — `pytest tests/ -v --timeout=120`
8. **Update CLAUDE.md** — reflect new architecture (SQLite, CEC, multi-user)
9. **Update README** — final polish with screenshots
10. **Tag release** — `git tag v2.1.0 && git push --tags`

---

## Execution Summary

| Phase | Batch | Branch | Depends On | Est. Tasks |
|-------|-------|--------|------------|------------|
| 1A | 1 | `fix/reliability` | PR #11 merged | 10 |
| 1B | 2 | `feature/sqlite-content-model` | Batch 1 | 6 |
| 2.1 | 3 | `feature/smart-slideshow` | Batch 2 | 9 |
| 2.2 | 4 | `feature/settings-ux` | Batch 2 | 6 |
| 2.3 | 5 | `feature/favorites-albums` | Batch 2 | 9 |
| 2.4 | 6 | `feature/multi-user-stats` | Batch 2 | 7 |
| 2.5 | 7 | `feature/hdmi-cec` | Batch 2 | 7 |
| 2.6 | 8 | `feature/security-docs` | Batch 2 | 8 |
| Review | — | main | All merged | 10 |

**Total: ~72 tasks across 8 batches + post-merge review**

Batches 3-8 are **fully parallel** (6 worktrees, no file overlap).
