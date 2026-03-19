# FrameCast v2 Polish — Gap Analysis & Feature Improvement Design

**Date:** 2026-03-19
**Status:** Approved
**Scope:** Reliability + polish + content control + HDMI-CEC + multi-user + stats
**Out of scope:** Cloud backup, remote monitoring dashboard
**Target:** All audiences (personal, gift-ready, public release)
**Hardware floor:** Pi 3 (1GB RAM, single-core, SD card)
**Data storage:** SQLite (`framecast.db`)

---

## Architecture Overview

```
Phase 0: Merge PR #11 (v2 foundation — already complete)
    │
Phase 1: Sequential Foundation
    ├─ PR-A: Reliability fixes (no schema change)
    └─ PR-B: SQLite schema + migration + PhotoCard extraction
    │
Phase 2: Parallel Fan-Out (6 independent worktrees)
    ├─ Agent 1: Smart Slideshow (rotation, transitions, Ken Burns)
    ├─ Agent 2: Settings & UX (complete settings, batch upload, onboarding)
    ├─ Agent 3: Favorites + Albums (content curation UI + API)
    ├─ Agent 4: Multi-user + Stats (user tracking, view counts, dashboard)
    ├─ Agent 5: HDMI-CEC (TV control, schedule wiring)
    └─ Agent 6: Security Hardening (firewall, PIN, smoke-test, docs)
```

**Dependency chain:** Phase 1A → Phase 1B → Phase 2 (all 6 agents parallel)

**File disjointness:** Each Phase 2 agent owns distinct files. No staging area conflicts.

---

## Mandatory Rules (From Lessons DB)

These apply to ALL agents and ALL code in this project:

| Rule | Lesson | Enforcement |
|------|--------|-------------|
| Never use `h` as callback parameter in JSX | #13 | CI grep check |
| All `except` blocks must log before returning fallback | #1418 | Hookify blocks bare except |
| All SQLite access via `contextlib.closing()` | #34, #1422 | Code review gate |
| All file writes use atomic pattern (tmp + fsync + rename) | #1234 | Code review gate |
| `PRAGMA journal_mode=WAL` + `busy_timeout=5000` on every open | #1335 | Set in `get_db()` |
| All subprocess `kill()`/`terminate()` wrapped in `suppress(ProcessLookupError)` | #81 | Code review gate |
| `daemon-reload` + `restart` after OTA, not just reload | #75 | Update script |
| Cache-bust static assets on OTA (version hash in filename) | #1318 | esbuild output hash |
| Toggle operations use atomic SQL (`UPDATE SET x = NOT x`) | #1274 | No read-then-write |
| DB row INSERT before file write, not after | #1670 | Upload order enforced |
| SSE cold-start: send current state on connect | #604 | First event is `state:current` |
| Gunicorn MUST run with workers=1 (singletons) | #1356 | Enforced in gunicorn.conf.py |

---

## Phase 1A: Reliability Fixes

Pure bug fixes and robustness improvements. No schema changes, no new features.

### 1. Kiosk Watchdog

**Problem:** GTK-WebKit crash or hang → black TV, no recovery.

**Fix:**
- `WatchdogSec=60` on `framecast-kiosk.service`
- `browser.js`: GJS calls `sd_notify('WATCHDOG=1')` every 30s via GLib subprocess
- Fallback: if WebKit fails to load 3x consecutively, display static error via framebuffer text

**Files:** `systemd/framecast-kiosk.service`, `kiosk/browser.js`

### 2. Health-Check Rollback Wiring

**Problem:** `health-check.sh` exists but isn't triggered by systemd. Rollback tag in world-writable `/tmp`.

**Fix:**
- Move rollback tag to `/var/lib/framecast/rollback-tag` (pi-gen creates dir, `pi:pi`, mode 700)
- HMAC signature alongside tag (using app secret)
- `framecast-health.service` + `framecast-health.timer` (90s after boot)
- `updater.py` writes to new location with signature
- Validate tag exists in git before checkout

**Files:** `scripts/health-check.sh`, `app/modules/updater.py`, `systemd/framecast-health.service` (new), `systemd/framecast-health.timer` (new), `pi-gen/stage2-framecast/03-system/`

### 3. Corrupt Image Handling

**Problem:** Malformed image crashes Pillow → upload handler 500. Bitrot after upload crashes slideshow.

**Fix:**
- Wrap `PILImage.open()` in try/except, quarantine bad files to `media/quarantine/`
- Call `verify()` after open for truncated image detection
- Slideshow: `onerror` handler skips to next after 3s
- Log quarantined files with reason

**Files:** `app/web_upload.py`, `app/modules/media.py`, `app/frontend/src/display/Slideshow.jsx`

### 4. WiFi AP Auto-Timeout

**Problem:** AP mode runs indefinitely. No rate limiting on connections.

**Fix:**
- 30-minute timeout: if no client connects within 30 min, restart AP
- Stop AP after successful onboarding
- Log AP state transitions
- Max 5 connection attempts/minute per MAC

**Files:** `app/modules/wifi.py`, `systemd/wifi-manager.service`

### 5. Smoke Test Fix (v1 References)

**Problem:** `scripts/smoke-test.sh` references v1 paths, services, VLC.

**Fix:**
- Paths → `/opt/framecast`
- Services → `framecast`, `framecast-kiosk`, `wifi-manager`
- Remove VLC checks, add kiosk checks
- Add frontend asset validation, Python syntax check
- Exit codes: 0 = pass, 1 = warnings, 2 = critical

**Files:** `scripts/smoke-test.sh`

### 6. Systemd Service Hardening

**Problem:** No start limits, weak dependency ordering, missing security directives.

**Fix:**
- `StartLimitIntervalSec=60` + `StartLimitBurst=5` on `framecast.service`
- `Requires=framecast.service` (not `Wants=`) on kiosk
- Add `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=true`, `NoNewPrivileges=true`
- `WatchdogSec=120` on `framecast.service`

**Files:** `systemd/framecast.service`, `systemd/framecast-kiosk.service`, `systemd/wifi-manager.service`, `systemd/framecast-update.service`

### 7. SSE Robustness

**Problem:** No heartbeat, no event coalescing, no exponential backoff.

**Fix:**
- Server: heartbeat every 20s (configurable `SSE_KEEPALIVE`)
- Client: exponential backoff on reconnect (1s → 2s → 4s → 8s, cap 60s)
- Event coalescing: debounce `photo:added` within 2s window
- `last-event-id` for reconnection gap recovery
- Cold-start replay: first event is `state:current` with full slideshow state (Lesson #604)
- Wrap SSE generator yield in try/except for BrokenPipeError + GeneratorExit (Lesson #36)

**Files:** `app/sse.py`, `app/frontend/src/display/Slideshow.jsx`, `app/frontend/src/pages/Upload.jsx`

### 8. Image Processing Timeout

**Problem:** Pillow operations have no timeout. Malformed image hangs upload thread.

**Fix:** Signal-based timeout wrapper (reuse existing `SIGALRM` pattern from `web_upload.py`). 30s timeout on any Pillow operation.

**Files:** `app/web_upload.py`

### 9. GPS Cache Fsync

**Problem:** `media.py` writes GPS cache without fsync (config.py does it correctly). Power loss corrupts cache.

**Fix:** Add `f.flush(); os.fsync(f.fileno())` before `Path.replace()` in `_save_locations_cache()`.

**Files:** `app/modules/media.py`

### 10. Gunicorn Graceful Timeout

**Problem:** `graceful_timeout=30` but request timeout is 120s. Large uploads killed on restart.

**Fix:** Set `graceful_timeout=120` to match. Also enforce `workers=1` (Lesson #1356):
```python
workers = 1  # MANDATORY — SSE, CEC, stats buffer are process-singletons
if os.environ.get("GUNICORN_WORKERS", "1") != "1":
    raise SystemExit("ERROR: FrameCast requires workers=1")
```

**Files:** `app/gunicorn.conf.py`

---

## Phase 1B: SQLite Schema + Migration

Foundation that all Phase 2 agents depend on.

### Database Location

`MEDIA_DIR/framecast.db` — co-located with photos for unified backup.

### Schema

```sql
CREATE TABLE photos (
    id INTEGER PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    filepath TEXT NOT NULL,
    mime_type TEXT,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    is_video BOOLEAN DEFAULT 0,
    checksum_sha256 TEXT,
    thumbnail_path TEXT,
    gps_lat REAL,
    gps_lon REAL,
    exif_date TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    uploaded_by TEXT DEFAULT 'default',
    is_favorite BOOLEAN DEFAULT 0,
    is_hidden BOOLEAN DEFAULT 0,
    view_count INTEGER DEFAULT 0,
    last_shown_at TEXT,
    quarantined BOOLEAN DEFAULT 0,
    quarantine_reason TEXT
);

CREATE TABLE albums (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE album_photos (
    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    PRIMARY KEY (album_id, photo_id)
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE photo_tags (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, tag_id)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    is_admin BOOLEAN DEFAULT 0,
    upload_count INTEGER DEFAULT 0,
    last_upload_at TEXT
);

CREATE TABLE display_stats (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    shown_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    duration_seconds REAL,
    transition_type TEXT
);

CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

-- Partial indices for Pi 3 performance
CREATE INDEX idx_photos_favorite ON photos(is_favorite) WHERE is_favorite = 1;
CREATE INDEX idx_photos_hidden ON photos(is_hidden) WHERE is_hidden = 0;
CREATE INDEX idx_photos_uploaded_by ON photos(uploaded_by);
CREATE INDEX idx_photos_last_shown ON photos(last_shown_at);
CREATE INDEX idx_display_stats_photo ON display_stats(photo_id);
CREATE INDEX idx_display_stats_shown ON display_stats(shown_at);
```

### DB Module: `app/modules/db.py`

- `get_db()` returns connection via `contextlib.closing()` (Lesson #34)
- WAL mode + `busy_timeout=5000` on every open (Lesson #1335)
- Write lock via `threading.Lock` (same pattern as config.py)
- Readers don't need lock (WAL allows concurrent reads)
- `init_db()` creates tables, runs migration, sets `schema_version`
- All toggle operations use atomic SQL: `UPDATE SET x = NOT x` (Lesson #1274)

### Migration Strategy

1. On first startup with DB, scan files in `MEDIA_DIR` (skip `quarantine/`, `thumbnails/`)
2. For each file: compute SHA256, extract EXIF, INSERT into photos
3. Import GPS cache into `photos.gps_lat`/`gps_lon`
4. Delete old JSON cache after successful migration
5. Create `default` user
6. Set `schema_version = 1`
7. Idempotent: if DB exists with matching version, skip

Edge cases:
- Symlinks: resolve but reject if outside MEDIA_DIR
- EXIF failure: INSERT with NULL metadata (don't skip)
- Log progress: "Migrating photo 47/312..."
- Interrupted migration: detect via schema_version, re-run

### Display Stats Buffering (SD Card Protection)

Stats accumulate in memory, flush to DB every 5 minutes:
```python
_stats_buffer = []

def record_view(photo_id, duration, transition):
    _stats_buffer.append((photo_id, duration, transition, now()))
    if len(_stats_buffer) >= 30:
        flush_stats()  # bulk INSERT, single DB write
```

Reduces SD writes from 8,640/day to ~288/day (50x reduction).

### DB Backup

On each OTA update (before git pull), copy `framecast.db` to `framecast.db.backup`.
Also expose `GET /api/backup` for manual download.

### Duplicate Detection

On upload, compute SHA256. If exists in DB, return `409 Conflict`. Skip file write.

### Upload Order (Lesson #1670)

```
validate image → INSERT photos (quarantined=1) → write file → fsync → UPDATE quarantined=0
```
Crash between INSERT and file write → quarantined row cleaned on startup.
Crash between file write and UPDATE → file exists but quarantined → migration picks it up.

### WAL Checkpoint Strategy

Explicit `PRAGMA wal_checkpoint(TRUNCATE)` after:
- Migration completion
- Batch upload completion (5+ files)
- Daily maintenance timer

### PhotoCard Extraction (Dependency Fix)

Extract individual photo card from PhotoGrid into `app/frontend/src/components/PhotoCard.jsx`.
Pure refactor — same markup, new file. This eliminates the file boundary conflict between Agent 2 (Upload.jsx) and Agent 3 (PhotoCard features).

### API Changes

Existing endpoints now query DB:
- `GET /api/photos` → `SELECT * FROM photos WHERE quarantined = 0 AND is_hidden = 0`
- `GET /api/locations` → `SELECT filename, gps_lat, gps_lon FROM photos WHERE gps_lat IS NOT NULL`
- `POST /upload` → INSERT into photos after file write
- `DELETE /api/photos/<name>` → `UPDATE quarantined = 1`, async file delete

New endpoints (consumed by Phase 2):
- `GET/POST /api/photos/<id>/favorite`
- `GET/POST/DELETE /api/albums`, `/api/albums/<id>/photos`
- `GET/POST/DELETE /api/tags`, `/api/photos/<id>/tags`
- `GET /api/stats`
- `GET /api/users`, `POST /api/users`, `DELETE /api/users/<id>`
- `GET /api/backup`

---

## Phase 2, Agent 1: Smart Slideshow

**Owns:** `app/modules/rotation.py` (new), `app/frontend/src/display/Slideshow.jsx`, `app/frontend/src/app.css`

### Weighted Rotation Algorithm

Replace flat shuffle with weighted selection:

```
Weight = base × recency_boost × favorite_boost × diversity_penalty

base           = 1.0
recency_boost  = 1.5 (uploaded < 7 days), 1.2 (< 30 days), 1.0 (else)
favorite_boost = 3.0 (is_favorite), 1.0 (else)
diversity_penalty = 0.1 (shown in last N slides, N = total × 0.3)
```

### Hybrid Playlist Architecture

Server computes weighted playlist of 50 photo IDs. Client fetches and plays locally.
New playlist requested when current one exhausts. This:
- Reduces API calls from 1/10s to 1/~8min
- Survives brief server downtime (plays cached playlist)
- Still benefits from DB-driven weighting

**API:** `GET /api/slideshow/playlist` → `{ "photos": [...], "playlist_id": "abc123" }`

### "On This Day" Feature

Once per hour, check for photos whose `exif_date` month+day matches today from a prior year.
If found, insert into playlist with subtle overlay text ("1 year ago" / "3 years ago").
Fallback to `uploaded_at` if `exif_date` is NULL.

### Transition Randomization

New setting: `TRANSITION_MODE` = `single` | `random`
- `single`: current behavior (one transition type for all)
- `random`: uniformly picks from fade/slide/kenburns/dissolve per slide
- Duration configurable: `TRANSITION_DURATION_MS` (default 1000, range 500-3000)

**Cut:** `smart` mode (match transition to content) — YAGNI.

### Ken Burns Improvements

- Randomize start/end positions (9 anchor points: TL, TC, TR, ML, MC, MR, BL, BC, BR)
- Scale range: 1.0→1.15 to 1.0→1.3, randomized per slide
- Aspect-aware: portrait → vertical pan, landscape → horizontal
- `will-change: transform` for GPU acceleration

### Video Handling

- Skip Ken Burns/transitions for video — direct play with fade-in/fade-out
- If decode fails (HEVC on Pi 3): log, set `quarantined=1` reason `"unsupported_codec"`, skip
- Cap video at `SLIDESHOW_DURATION × 3` (30s max for 10s interval)

### Tests

- Unit tests for `rotation.py`: weighted distribution, "on this day" logic, diversity penalty, playlist generation
- Verify no `h` callback parameters in JSX

---

## Phase 2, Agent 2: Settings & UX Polish

**Owns:** `app/frontend/src/pages/Settings.jsx`, `app/frontend/src/pages/Upload.jsx`, `app/frontend/src/pages/Onboard.jsx`, `app/frontend/src/components/`, `app/frontend/src/app.css`

### First-Boot Onboarding Wizard

**Critical for gift-ready.** Auto-redirect on first boot (`ONBOARDING_COMPLETE=0`).

4-step wizard:
1. **Welcome** — QR code on TV + plain-text: "Scan with phone to set up"
2. **WiFi** — existing WiFi scan/connect flow (extracted from current Onboard page)
3. **Upload First Photo** — ShDropzone with encouraging copy
4. **Done** — "Your frame is ready!" + redirect to slideshow

TV display shows large QR code + simple instructions throughout.
Config flag `ONBOARDING_COMPLETE=1` on completion. Never shows again.

### Complete Settings Page

**Display Section** (existing, enhance):
- Transition mode: single/random dropdown
- Transition duration: slider 500-3000ms
- Ken Burns intensity: subtle/moderate/dramatic

**Security Section** (new):
- PIN change: input + "Regenerate" button
- PIN strength: 4/6-digit toggle

**Schedule Section** (new):
- Display on/off times (HH:MM pickers → HDMI control)
- Days of week selector
- Manual on/off toggle (immediate)

**Network Section** (new, read-only):
- Current WiFi SSID + signal
- IP address + hostname
- Connected SSE clients count

**System Section** (new):
- Storage bar (existing, move here)
- Version + update status
- Restart services button (guarded by confirm modal)

### Batch Upload Progress

- "Uploading file 3 of 12" text
- Per-file progress indicators
- Auto-retry failed uploads (3 attempts, exponential backoff)
- Estimated time remaining
- Completion summary with error details

### Error States & Loading

- `fetch()` timeout: 15s default, 60s uploads
- Offline detection: `navigator.onLine` + SSE state → banner
- Settings load failure: "Retry" button
- Validation: `aria-invalid` + `aria-describedby` per field
- Rate limit: 429 → "Too many requests, try again in Xs"

### Accessibility

- Focus trap on PinGate + delete modals
- `<main>`, `<nav>`, `<section>` landmarks
- Signal bars: `aria-label="Signal strength: 80%"`
- Map tooltips: `aria-hidden` / `role="tooltip"`
- Toast: above nav bar

### Tests

- Python endpoint tests for settings API
- Verify landmarks and aria attributes in component markup

---

## Phase 2, Agent 3: Favorites + Albums

**Owns:** `app/frontend/src/components/PhotoCard.jsx` (feature additions), `app/frontend/src/components/Lightbox.jsx` (new), `app/frontend/src/pages/Albums.jsx` (new), `app/web_upload.py` (favorite/album/tag API endpoints)

### PhotoCard Enhancements

PhotoCard.jsx (extracted in Phase 1B) gets new features:
- Favorite toggle: gold star, one tap, calls `POST /api/photos/{id}/favorite`
- Selection mode: checkbox for bulk actions
- Long-press: context menu (favorite, add to album, delete, info)
- Tap: opens Lightbox

### Favorites

- Filter on Upload page: "All | Favorites | Hidden"
- Favorites count badge in nav
- SSE event: `photo:favorited` triggers UI refresh

### Albums Page (new)

- Grid of album covers (first photo or user-selected)
- Create: name + optional description
- Add photos: select mode → "Add to Album"
- Album detail: photo grid, reorderable
- Delete album (photos unlinked, not deleted)

### Smart Albums (computed, not stored)

Predefined queries returned from `GET /api/albums` with `smart: true`:
```python
SMART_ALBUMS = {
    "recent": "uploaded_at > datetime('now', '-30 days')",
    "on_this_day": "strftime('%m-%d', exif_date) = strftime('%m-%d', 'now')",
    "most_shown": "ORDER BY view_count DESC LIMIT 20",
}
```
No DB rows, no sync, no cleanup.

### Tags

- Tag chips in Lightbox view
- Auto-suggest from existing tags
- Slideshow filter: `SLIDESHOW_TAGS` setting
- Bulk tag via selection mode

### Lightbox (new)

- Full-screen preview on tap
- Swipe left/right to navigate
- Bottom bar: favorite, add to album, delete, info (EXIF, dates, view count)
- Pinch-to-zoom on mobile
- `Escape` / swipe-down to close

### Tests

- DB query tests: favorites CRUD, album CRUD, tag CRUD
- Smart album query validation

---

## Phase 2, Agent 4: Multi-User + Stats

**Owns:** `app/modules/users.py` (new), `app/frontend/src/pages/Stats.jsx` (new), `app/frontend/src/pages/Users.jsx` (new), `app/web_upload.py` (user endpoints)

### Multi-User Model

Lightweight, no passwords:
- First upload: "Who's uploading?" prompt with user list + "New person"
- Cookie `framecast_user` (30 days)
- All uploads tagged `uploaded_by`
- User switcher in nav (initial icon)

**API:**
- `GET /api/users` — list with upload counts
- `POST /api/users` — create (name only)
- `DELETE /api/users/<id>` — remove (photos → 'default')

### Per-User Filtering

- Upload page: "My photos" / "All" / specific user filter
- Settings: `SLIDESHOW_USER_FILTER` toggle
- Stats: per-user history

### Stats Dashboard

Accessible from Settings → "View Stats" or nav icon.

**Metrics (all from DB queries, no external analytics):**
- Total photos/videos/storage
- Photos by user (superhot-ui table)
- Upload timeline (ASCII-style bar, terminal aesthetic)
- Most shown top 10 (by view_count)
- Least shown bottom 10 ("neglected" — aids curation)
- Average display time
- Slideshow uptime
- "On This Day" preview

### Tests

- DB query tests: stats aggregation, user CRUD
- Empty-state validation (fresh DB returns valid responses, not 500)

---

## Phase 2, Agent 5: HDMI-CEC

**Owns:** `app/modules/cec.py` (new), `scripts/hdmi-control.sh` (rewrite), systemd units

### CEC via cec-client

Shell out to `cec-client` (no Python CEC library — all unmaintained).

```python
def tv_power_on() -> bool: ...
def tv_standby() -> bool: ...
def tv_status() -> str: ...      # "on", "standby", "unknown"
def set_active_source() -> bool: ...
```

All commands: 5s timeout, logged, return False on failure. Design for graceful degradation.

### CEC Init (Lesson #7)

Must query TV state on startup, not assume:
```python
def init_cec():
    status = tv_status()
    log.info("CEC init: TV is %s", status)
    if status == "unknown":
        log.warning("CEC: TV not responding — will retry on schedule")
```

### HDMI Schedule

CEC-first, `wlr-randr` fallback:
1. Try CEC standby → if fails, `wlr-randr --output <detected> --off`
2. Dynamic output detection: `wlr-randr | grep -oP 'HDMI-\S+'`

New systemd units:
- `framecast-schedule.timer` (runs every minute)
- `framecast-schedule.service` checks time vs schedule, calls CEC

Settings: `DISPLAY_ON_TIME`, `DISPLAY_OFF_TIME`, `DISPLAY_SCHEDULE_DAYS`

### Pi-Gen Package

Add `cec-utils` to `pi-gen/stage2-framecast/01-packages/00-packages`.

### Tests

- Mock subprocess: verify command strings, timeout handling
- CEC init state query test
- `suppress(ProcessLookupError)` on all kill/terminate (Lesson #81)

---

## Phase 2, Agent 6: Security Hardening + Docs

**Owns:** `pi-gen/`, `scripts/smoke-test.sh`, `app/modules/auth.py`, `app/modules/updater.py`, `README.md`, `CONTRIBUTING.md`, `API.md`

### Firewall (ufw)

- Install `ufw` in pi-gen packages
- Default deny incoming, allow outgoing
- Allow 8080/tcp from RFC1918 (`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`)
- Allow mDNS (port 5353)
- Enable at boot

### Stronger PIN

- `PIN_LENGTH` setting: 4 or 6 digits (default 4)
- Rate limiting: 5 attempts/5-min for 4-digit, 3 attempts/5-min for 6-digit
- `PIN_ROTATE_ON_BOOT` option (default false)
- Log PIN attempts at WARN level

### Rollback Tag Hardening

- `/var/lib/framecast/` created by pi-gen (pi:pi, mode 700)
- HMAC signature on rollback tag
- `health-check.sh` validates HMAC before trusting
- Validate tag in git before checkout

### Update Signing

- After `git fetch`, verify tag commit SHA matches GitHub API response
- SHA256 pinning (not full GPG)

### Smoke Test Rewrite

Full rewrite of `scripts/smoke-test.sh`:
- Paths: `/opt/framecast`
- Services: `framecast`, `framecast-kiosk`, `wifi-manager`, `framecast-update`
- No VLC checks, add kiosk checks
- Frontend asset validation
- Python syntax check (`python3 -m py_compile`)
- DB existence check
- `systemd-analyze verify` on unit files
- Exit codes: 0 pass, 1 warnings, 2 critical

### Additional Security

- `SameSite=Strict` on cookies + validate `Origin` header
- `python3-magic` for MIME type validation (defense-in-depth)
- API rate limiting: 60 req/min per IP (in-memory counter)
- `Secure` cookie flag when HTTPS detected

### Documentation (Public Release)

- **README.md** update: v2 features, setup guide, screenshots, troubleshooting
- **CONTRIBUTING.md**: architecture overview, dev setup, PR guidelines
- **API.md**: all endpoints documented with request/response examples
- **Troubleshooting section**: WiFi won't connect, TV is black, photos not showing

### Tests

- Smoke test is itself a test — validate it runs clean
- Auth rate limiter unit tests

---

## Scope Cuts (Deferred to v2.1)

| Feature | Reason | Issue |
|---------|--------|-------|
| Motion sensor (PIR) | No named users, hypothetical hardware | Create #13 |
| Smart transitions (match to content) | Random sufficient, smart is over-engineered | — |
| Export photos as zip | Pi 3 OOM risk on large collections | Create #14 |
| Cloud backup | Out of scope per requirements | — |
| Remote monitoring | Out of scope per requirements | — |

---

## File Ownership Map (Phase 2)

| Agent | Files Owned | Shared (Read-Only) |
|-------|-------------|---------------------|
| 1: Slideshow | `rotation.py`, `Slideshow.jsx`, `app.css` (transitions only) | `db.py` |
| 2: Settings | `Settings.jsx`, `Upload.jsx`, `Onboard.jsx`, `app.css` (layout) | `db.py`, `PhotoCard.jsx` (import) |
| 3: Albums | `PhotoCard.jsx` (features), `Lightbox.jsx`, `Albums.jsx`, album API routes | `db.py` |
| 4: Multi-user | `users.py`, `Stats.jsx`, `Users.jsx`, user API routes | `db.py` |
| 5: CEC | `cec.py`, `hdmi-control.sh`, schedule systemd units | — |
| 6: Security | `pi-gen/`, `smoke-test.sh`, `auth.py`, `updater.py`, docs | — |

**Conflict zone:** Agents 1 and 2 both touch `app.css` — Agent 1 owns transition CSS, Agent 2 owns layout/responsive CSS. Different sections, low collision risk.

---

## Test Plan

Each agent produces tests:

| Agent | Test Type | Scope |
|-------|-----------|-------|
| Phase 1A | Integration | Health-check + rollback, SSE reconnect, image quarantine |
| Phase 1B | Unit | DB CRUD, migration idempotency, duplicate detection |
| Agent 1 | Unit | Weighted rotation distribution, "on this day", playlist generation |
| Agent 2 | Unit + Manual | Settings API, onboarding flow (manual on device) |
| Agent 3 | Unit | Favorites/albums/tags CRUD, smart album queries |
| Agent 4 | Unit | Stats aggregation, user CRUD, empty-state responses |
| Agent 5 | Unit | CEC command strings, timeout handling, init state query |
| Agent 6 | Integration | Smoke test runs clean, rate limiter, HMAC validation |

---

## References

- Design doc: `docs/plans/2026-03-19-framecast-image-design.md`
- Implementation plan: `docs/plans/2026-03-19-framecast-image-plan.md`
- Pi-gen research: `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md`
- Display stack research: `docs/plans/2026-03-19-mpv-vs-vlc-display-stack-research.md`
- V2 polish research: `docs/plans/2026-03-19-v2-polish-research.md` (pending)
- Lessons DB: `~/.local/share/lessons-db/lessons.db` (34 relevant lessons surfaced)
