# FrameCast v2 Polish Research — Open-Source Implementation Survey

**Date:** 2026-03-19
**Status:** Complete
**Purpose:** Mandatory Google Feature Implementation search (Code Factory workflow) for FrameCast v2 features: database content model, HDMI-CEC control, smart photo rotation, and multi-user support.

---

## 1. Pi Photo Frame Projects with Database Content Models

### 1a. PhotoPrism (AI-Powered Photo Management)

- **Repository:** https://github.com/photoprism/photoprism
- **Stars:** ~36k (largest project in this space by far)
- **Stack:** Go backend, MariaDB/SQLite, Vue.js frontend

**Schema patterns to borrow:**

PhotoPrism's data model is the gold standard for photo metadata. Core entities:

| Entity | Key Fields | Notes |
|--------|-----------|-------|
| `Photo` | ID, UID, Title, TakenAt, TakenAtLocal, Favorite (bool), Private (bool), Lat/Lng, Type | `Favorite` is a simple boolean toggle — no rating scale |
| `Album` | Title, Slug, Type (manual/folder/moment/month/state), Category, Favorite, Privacy, Country, Year/Month/Day | Multiple album types auto-generated from metadata |
| `File` | Photo FK, Name, Hash, Width, Height, Size, Codec, Duration | One-to-many with Photo |
| `Label` | Name, Slug, Priority, Favorite | Many-to-many with Photo via join table |
| `PhotoAlbum` | Photo FK, Album FK, Order, Hidden | Join table with ordering support |
| `Subject` / `Marker` | Face detection + people identification | Many-to-many via markers on photos |

**Key patterns:**
- **Album types are polymorphic** — same table stores user-created albums, auto-generated "moments" (events), monthly groupings, and geography-based collections. This is cleaner than separate tables.
- **Favorites are booleans on multiple entities** — photos, albums, and labels can all be favorited. Simple and effective.
- **`toggleLike()` API** — single endpoint toggles favorite status. No separate add/remove.
- **Separate `Details` entity** for extended metadata (description, notes, keywords) avoids bloating the main photo table.

**Known limitations:**
- SQLite performance degrades with large libraries (>50k photos). They recommend MariaDB for production. On a Pi, this is relevant — SQLite with proper indexing should be fine for <10k photos typical of a family frame.
- Multi-user support is still incomplete (single-user only as of writing). Community has been requesting it since 2020 (Issue #98, Discussion #1678).

**What to adopt:** Album type polymorphism, boolean favorites, separate Details entity.
**What they don't do:** No display scheduling, no "on this day" memories, no per-device display preferences.

### 1b. ePiframe (e-Paper/HDMI Pi Photo Frame)

- **Repository:** https://github.com/MikeGawi/ePiframe
- **Stars:** 73
- **Stack:** Python, SQLite, Dropzone.js, RRDtool

**Architecture:**
Autonomous standalone device — once configured, runs headless with systemd service auto-recovery. Pulls from Google Photos albums and/or local folders. Web UI for configuration and file upload.

**Photo selection model:**
- Filtering by creation date and count
- Display order: random, ascending, or descending by date
- Per-photo display duration customizable via "hot word" metadata in photo descriptions
- Plugin architecture for custom photo sources and processing

**Known limitations:**
- **Google Photos API died** (Issue #114) — only local source currently works. This is a cautionary tale for FrameCast: never depend on a cloud API as the primary source.
- No favorites or per-photo weighting in the selection algorithm
- No multi-user support

**What to adopt:** The hot-word metadata concept (embed display hints in photo descriptions/tags) is clever for power users. Plugin architecture for photo sources is good design even if FrameCast starts local-only.
**What they don't do:** No smart rotation, no favorites weighting, no "on this day."

### 1c. MiFrame (Client-Server Multi-Frame)

- **Repository:** https://github.com/tklenke/miframe
- **Stars:** 1
- **Stack:** Python, Flask, INI config, external USB drive

**Architecture:**
True client-server model where multiple Pi frames connect to a single MiFrame-Server. Central server distributes photos to all frames over the network.

**Key features:**
- Shared database across multiple frames
- Per-photo actions via web browser: Liked, Blocked, Rotated
- Multi-frame serving from single server

**Known limitations:**
- Minimal documentation, incomplete setup instructions
- No formal database schema documented (uses INI config files)
- 1 star — essentially a proof of concept
- Requires external USB drive for storage

**What to adopt:** The Like/Block/Rotate user action model is the right set of per-photo controls for a family frame. The multi-frame-from-single-server architecture is interesting for v3+ but overkill for v2.
**What they don't do:** No smart selection algorithm, no albums, no on-device database.

### 1d. Recommended FrameCast v2 Schema

Based on patterns across all surveyed projects, recommended SQLite schema for FrameCast:

```sql
-- Core photo metadata
CREATE TABLE photos (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    original_filename TEXT,
    file_hash TEXT UNIQUE,           -- SHA256 for dedup
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    mime_type TEXT,
    taken_at TIMESTAMP,              -- EXIF date
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by INTEGER REFERENCES users(id),
    latitude REAL,
    longitude REAL,
    favorite INTEGER DEFAULT 0,      -- boolean (PhotoPrism pattern)
    hidden INTEGER DEFAULT 0,        -- soft-hide from rotation
    display_count INTEGER DEFAULT 0, -- track how often shown
    last_displayed_at TIMESTAMP,     -- for recency balancing
    exif_json TEXT                   -- full EXIF as JSON blob
);

-- Albums (polymorphic type, PhotoPrism pattern)
CREATE TABLE albums (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'manual',      -- manual | auto_date | auto_location
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sort_order TEXT DEFAULT 'random'  -- random | newest | oldest | alpha
);

-- Photo-album join
CREATE TABLE photo_albums (
    photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    album_id INTEGER REFERENCES albums(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    PRIMARY KEY (photo_id, album_id)
);

-- Tags (lightweight labels)
CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE photo_tags (
    photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, tag_id)
);

-- Users (multi-user upload tracking)
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    upload_count INTEGER DEFAULT 0
);

-- Display schedule / active album selection
CREATE TABLE display_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

**Key indices:** `photos(taken_at)`, `photos(favorite)`, `photos(uploaded_at)`, `photos(display_count)`, `photos(last_displayed_at)`.

---

## 2. HDMI-CEC Python/Bash Libraries

### Critical Finding: cec-client is deprecated

**The biggest takeaway from this research:** `libcec` and `cec-client` are effectively dead projects. On Raspberry Pi OS Bookworm (which FrameCast targets), `cec-utils` (libcec) has been broken for multiple releases. The Raspberry Pi engineering team recommends migrating to the **Linux CEC API** via `cec-ctl` from `v4l-utils`.

**Recommendation:** FrameCast v2 should use `cec-ctl` (v4l-utils), NOT `cec-client` (libcec).

### 2a. cec-ctl (v4l-utils) — Recommended

- **Package:** `v4l-utils` (maintained as part of Linux kernel tooling)
- **Man page:** https://manpages.debian.org/testing/v4l-utils/cec-ctl.1.en.html

**Command reference:**

| Action | Command |
|--------|---------|
| Power on TV | `cec-ctl -d/dev/cec0 --to 0 --image-view-on` |
| Standby TV | `cec-ctl -d/dev/cec0 --to 0 --standby` |
| Set active source | `cec-ctl -d/dev/cec0 --to 0 --active-source phys-addr=X.X.X.X` |
| Scan topology | `cec-ctl -d/dev/cec0 --playback -S` |
| List CEC devices | `cec-ctl -A` (list all `/dev/cecX` devices) |
| Monitor CEC bus | `cec-ctl -d/dev/cec0 -m` |

**Pi-specific notes:**
- Pi 5: `tvservice` is deprecated. Use `kmsprint` + `cec-ctl` instead.
- CEC requires `vc4-kms-v3d` overlay (not `fkms`). FrameCast's pi-gen stage already uses KMS.
- On Pi 5, HDMI-0 (closest to power port) is more reliable for CEC than HDMI-1.
- Device path is `/dev/cec0` (Pi 3/4 single HDMI) or `/dev/cec0`/`/dev/cec1` (Pi 4/5 dual HDMI).

**Failure modes (common across ALL CEC implementations):**
1. **TV doesn't support standby opcode** — Samsung TVs need "Anynet+ (HDMI-CEC)" enabled in settings. Some TVs only support subset of CEC.
2. **Power status returns "unknown"** — some TVs don't respond to status queries. Workaround: assume last-sent command succeeded.
3. **CEC stops working after extended runtime** — libcec-specific bug, less common with cec-ctl. Workaround: reset CEC adapter on failure.
4. **Pi turns off before CEC command completes** — CEC init is slow (~2-5s). On shutdown, send standby early via ExecStop.
5. **Not all HDMI ports support CEC** — TV-side limitation. Port 1 (ARC) is most reliable.
6. **HDMI cable quality matters** — cheap cables sometimes don't pass CEC pin (pin 13).

### 2b. python-cec (for reference, NOT recommended for FrameCast)

- **Repository:** https://github.com/trainman419/python-cec
- **Stars:** 179
- **Stack:** C++ extension wrapping libcec

**API:**
- `power_on()`, `standby()`, `is_on()` — device power control
- `set_av_input(input)`, `set_audio_input(input)` — input switching
- `set_active_source()`, `is_active_source(addr)` — source management
- Event callbacks: `EVENT_LOG`, `EVENT_KEYPRESS`, `EVENT_COMMAND`, `EVENT_ALERT`
- Device discovery: `cec.list_adapters()`, `cec.list_devices()`

**Why NOT to use it:**
- Depends on libcec (broken on Bookworm)
- C++ compilation required (painful on Pi, slow)
- Version compatibility issues across libcec versions (2.x vs 3.x vs 5.x)
- Previous deadlock issues (fixed but concerning)

### 2c. pyCEC (Home Assistant bridge)

- **Repository:** https://github.com/konikvranik/pyCEC
- **Stars:** 52
- **Stack:** Python, TCP bridge, libcec

**Architecture:** TCP server (port 9526) that bridges network commands to HDMI-CEC. Used by Home Assistant's `hdmi_cec` integration.

**Interesting pattern:** The TCP bridge concept means CEC commands can come from anywhere on the network, not just the Pi connected to the TV. Useful if FrameCast ever needs remote CEC control.

**Why NOT to use it:**
- Same libcec dependency problem
- Requires `--system-site-packages` in virtualenvs
- Overkill for a single-device photo frame

### 2d. Raspberry-Pi-CEC-controller (bash wrapper)

- **Repository:** https://github.com/mkokshoorn/Raspberry-Pi-CEC-controller
- **Stars:** 1
- **Stack:** Python functions wrapping `cec-client` subprocess calls

**Pattern to borrow:** The subprocess wrapper approach is correct for FrameCast — call `cec-ctl` via `subprocess.run()` rather than importing a C library. Keeps dependencies minimal and avoids libcec entirely.

### 2e. MMM-CECControl (MagicMirror module)

- **Repository:** https://github.com/nischi/MMM-CECControl
- **Stars:** 14
- **Stack:** Node.js, cec-utils subprocess

**Interesting patterns:**
- `offOnStartup` config option — auto-off when module starts (useful for FrameCast's HDMI schedule)
- Fallback to custom shell commands if CEC doesn't work: `useCustomCmd`, `customCmdOn/Off`
- Stateless design — sends commands without tracking TV state

**What to adopt:** The custom command fallback is smart. FrameCast should allow users to configure alternative power commands (e.g., `wlr-randr --output HDMI-A-1 --off` for display blanking if CEC fails).

### 2f. Recommended FrameCast v2 CEC Implementation

```python
# scripts/hdmi-cec.py — thin wrapper around cec-ctl
import subprocess
import logging

CEC_DEVICE = "/dev/cec0"  # auto-detect via cec-ctl -A

def cec_cmd(*args):
    """Run cec-ctl command, return (success, output)."""
    cmd = ["cec-ctl", f"-d{CEC_DEVICE}"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0, result.stdout
    except subprocess.TimeoutExpired:
        logging.warning("CEC command timed out: %s", args)
        return False, ""

def tv_on():
    return cec_cmd("--to", "0", "--image-view-on")

def tv_off():
    return cec_cmd("--to", "0", "--standby")

def tv_active_source(phys_addr="1.0.0.0"):
    return cec_cmd("--to", "0", f"--active-source", f"phys-addr={phys_addr}")

def scan_devices():
    return cec_cmd("--playback", "-S")
```

**Package dependency:** `v4l-utils` (add to pi-gen `00-packages`).

---

## 3. Smart Photo Rotation Algorithms

### 3a. Weighted Random Selection Algorithms

Four established algorithms for weighted random selection, ranked by suitability for FrameCast:

| Algorithm | Selection Time | Setup Time | Memory | Best For |
|-----------|---------------|------------|--------|----------|
| **Alias Method (Vose)** | O(1) | O(n) | O(n) | Large collections, frequent selections |
| **Binary CDF Search** | O(log n) | O(n) | O(n) | Medium collections, simple implementation |
| **Linear CDF Search** | O(n) | O(n) | O(n) | Small collections (<100 photos) |
| **Repetition** | O(1) | O(n*w) | O(n*w) | Never — wastes memory |

**Recommendation:** Binary CDF Search for FrameCast v2. The Alias Method is theoretically optimal but overkill for <10k photos where selections happen every 10-60 seconds. Binary CDF is simpler to implement, debug, and the O(log n) lookup is imperceptible.

Source: https://zliu.org/post/weighted-random/ — comprehensive comparison with Go implementations.

### 3b. Weight Calculation Model

Synthesized from Apple Photos signals, Immich memories, and recommendation system patterns:

**Base weight formula:**
```
weight(photo) = W_recency * recency_score
              + W_favorite * favorite_boost
              + W_freshness * freshness_score
              + W_diversity * diversity_penalty
              + W_memory * memory_boost
```

**Component scores:**

1. **Recency score** (boost recently uploaded photos):
   - Half-life decay: `score = 2^(-days_since_upload / half_life)`
   - Recommended half-life: 7 days (photo gets 50% boost for first week, decays to baseline over ~30 days)
   - Source: Half-life decay model from recommendation systems literature

2. **Favorite boost** (show favorites more often):
   - Binary multiplier: `favorite_boost = 3.0 if photo.favorite else 1.0`
   - Simple and effective — favorites appear ~3x more often

3. **Freshness score** (avoid showing same photo repeatedly):
   - Inverse of display count: `score = 1.0 / (1 + display_count)`
   - Combined with time since last shown: penalize if `last_displayed_at` was recent
   - Prevents the "same 10 photos" problem

4. **Diversity penalty** (avoid clustering by upload batch):
   - If last 3 shown photos were from same upload batch (within 1 hour of each other), penalize remaining batch members
   - Prevents "all vacation photos in a row" when someone uploads 50 at once

5. **Memory boost** ("On This Day" feature):
   - If `photo.taken_at` matches today's month+day from a previous year: `memory_boost = 5.0`
   - Query: `WHERE strftime('%m-%d', taken_at) = strftime('%m-%d', 'now') AND strftime('%Y', taken_at) < strftime('%Y', 'now')`
   - This is how Immich and Apple Photos both implement "On This Day"

**Recommended default weights:**
```python
WEIGHTS = {
    'recency': 0.20,    # 20% influence from upload date
    'favorite': 0.25,   # 25% influence from favorite status
    'freshness': 0.30,  # 30% influence from display frequency (most important)
    'diversity': 0.10,  # 10% anti-clustering
    'memory': 0.15,     # 15% "on this day" boost
}
```

### 3c. "On This Day" / Memories Implementation

**How Immich does it:**
- Job-based: `Administration/Jobs/Create new job/Memory generation`
- Matches assets from previous years on the same date
- Also supports "trip memories" — photos from atypical locations within a week of the current date in past years
- Exposed via REST API: `/api/memories` endpoint
- ImmichFrame (companion project) can pull "On This Day" memories for display

**How Apple Photos does it:**
- ML-scored selection from photos matching today's date in previous years
- Signals: People identification, view frequency, favorite status, explicit removals
- Categories: People, Pets, Nature, Cities — user selects which to include
- Proprietary algorithm, but the inputs are known

**FrameCast implementation (recommended):**
- No ML needed. Simple date matching on `taken_at` EXIF data.
- Query for "on this day" candidates at midnight (or on settings change):
  ```sql
  SELECT * FROM photos
  WHERE strftime('%m-%d', taken_at) = strftime('%m-%d', 'now')
  AND strftime('%Y', taken_at) < strftime('%Y', 'now')
  AND hidden = 0
  ORDER BY taken_at DESC;
  ```
- If matches found, inject them into the weighted rotation with a 5x boost
- Optionally show a brief overlay: "3 YEARS AGO TODAY" with the date
- Settings toggle: enable/disable "On This Day" feature

### 3d. What Commercial Frames Do

**Nixplay:**
- Playlist-based shuffle within user-created playlists
- Configurable transition duration and shuffle on/off
- Motion sensor to wake/sleep display
- No documented smart weighting or "on this day"

**Aura:**
- "Intelligent photo curation" (proprietary, likely basic ML)
- Shows photos from friends/family who've shared to the frame
- No public documentation on selection algorithm

**Skylight:**
- Email-to-frame model (email a photo, it appears on the frame)
- No local storage management
- Simple FIFO display with manual reordering

**Gap/opportunity:** None of the commercial frames expose their photo selection algorithm or let users tune weights. FrameCast can differentiate by making the rotation algorithm transparent and configurable — power users can tune weights, everyone else gets good defaults.

---

## 4. Multi-User Photo Frame Systems

### 4a. Photoview (Self-Hosted Gallery)

- **Repository:** https://github.com/photoview/photoview
- **Stars:** 6,400
- **Stack:** Go backend, React frontend, SQLite/MariaDB/PostgreSQL

**Multi-user model:**
- Each user created with a filesystem path — photos within that path are accessible to that user
- Albums and individual media shareable via password-protected public links
- Role-based access: admin vs regular user
- Face recognition groups photos by person automatically

**Key patterns:**
- **Path-based permissions** — simple and filesystem-native. No complex ACL tables.
- **Share links with optional passwords** — clean UX for sharing outside the household
- **RAW file support** + automatic thumbnail generation

**What to adopt:** The password-protected share link pattern is useful if FrameCast ever supports remote photo submission (share a link, anyone with it can upload).
**Limitation:** Not designed for a display device — it's a gallery browser. No slideshow mode, no display scheduling.

### 4b. Lychee (Self-Hosted Photo Management)

- **Repository:** https://github.com/LycheeOrg/Lychee
- **Stars:** 4,100
- **Stack:** PHP/Laravel, SQLite/MariaDB/PostgreSQL, Vue.js

**Multi-user model:**
- Full user management with distinct permission levels
- Album-level sharing with granular access control
- Public/private album toggle
- User-specific upload quotas possible

**What to adopt:** Laravel's migration-based schema evolution is a good pattern. FrameCast's SQLite schema should use versioned migrations from day one.
**Limitation:** Heavy stack (PHP/Laravel) — not suitable for Pi resource constraints. But the permission model design is solid reference material.

### 4c. photOS (WebDAV Photo Frame OS)

- **Repository:** https://github.com/avanc/photOS
- **Stars:** 119
- **Stack:** Buildroot, C/C++, Python, framebuffer-direct rendering

**Multi-user model:**
- Syncs photos with a WebDAV server (e.g., Nextcloud)
- Family members upload via Nextcloud's mobile app to the shared WebDAV folder
- Frame pulls new photos automatically — works offline with cached content

**Architecture:**
- Custom Linux OS built with Buildroot (not pi-gen)
- Direct framebuffer rendering (no browser, no X11, no Wayland)
- HDMI power management via motion detection
- Minimal resource footprint (targets Pi Zero W)

**What to adopt:** The WebDAV sync model is a clean alternative to direct upload for tech-savvy families. Could be a v3 feature — sync from Nextcloud/Immich instead of only manual upload.
**Limitation:** Very low-level (framebuffer), no web UI, no albums or favorites, last release Dec 2021 (appears dormant).

### 4d. ImmichFrame (Immich Companion for Frames)

- **Repository:** https://github.com/immichFrame/ImmichFrame (community project)
- **Documentation:** https://pixelunion.eu/blog/immichframe/
- **Stack:** Separate server + web/Android display clients

**Multi-user model:**
- **Multi-account support** — combine multiple Immich accounts into one ImmichFrame instance
- Unifies a family's separate photo libraries onto one frame
- Pull from specific albums, people, "On this day" memories, favorites, or date ranges per account

**Architecture:**
- Separate server alongside Immich — fetches photos via Immich API
- Web UI for configuration
- Dedicated display clients (Android app, web browser)
- Album selection by ID, transition duration control, pan animation

**What to adopt:** The "combine multiple accounts" concept is the cleanest multi-user model for a family frame. Each family member has their own account/identity; the frame aggregates. For FrameCast v2, this maps to: each `user` in the database represents a family member, photos track `uploaded_by`, and display settings can optionally filter by user.

### 4e. Recommended FrameCast v2 Multi-User Model

**Complexity level: Light.** Full RBAC is overkill for a family photo frame. Recommended approach:

1. **Named uploaders** (not authenticated users):
   - On first upload from a new device, prompt for a name: "WHO ARE YOU?" with text input
   - Store as a `user` record, set cookie on device (30-day expiry, same as PIN)
   - All subsequent uploads tagged with that user
   - No passwords, no accounts — the PIN protects the frame, user identity is social

2. **Per-user upload tracking:**
   - `photos.uploaded_by` FK to `users.id`
   - Upload page shows: "ALICE: 47 PHOTOS | BOB: 23 PHOTOS | CAROL: 12 PHOTOS"
   - Optional filter: show only Alice's photos (useful for debugging "who uploaded that?")

3. **Per-user display weight (v2+):**
   - Settings option: "EQUAL TIME" — weight display so each uploader gets roughly equal screen time
   - Prevents one person's 500 vacation photos from drowning out others' 10 photos
   - Implementation: multiply photo weight by `1.0 / user_upload_count` (normalized)

4. **No permissions model in v2:**
   - Anyone with the PIN can upload and delete any photo
   - v3 consideration: per-user delete permissions (can only delete own photos)

---

## 5. Cross-Cutting Findings

### Architecture Patterns to Borrow

| Pattern | Source | Apply To |
|---------|--------|----------|
| Boolean favorites on photos | PhotoPrism | `photos.favorite` column |
| Polymorphic album types | PhotoPrism | `albums.type` = manual/auto_date/auto_location |
| Subprocess CEC wrapper | RPi-CEC-controller, MMM-CECControl | `cec-ctl` via `subprocess.run()` |
| Custom command fallback | MMM-CECControl | If CEC fails, fall back to `wlr-randr` for display blanking |
| Named uploaders (cookied) | ImmichFrame multi-account concept | Lightweight user identity without authentication |
| Half-life decay for recency | Recommendation systems literature | Photo weight decays from upload date |
| Date-match for memories | Immich, Apple Photos | `strftime('%m-%d', taken_at)` match |
| Share via password-protected link | Photoview | v3 feature for remote photo submission |

### Known Failure Modes to Design Around

| Failure Mode | Observed In | FrameCast Mitigation |
|-------------|------------|---------------------|
| Cloud API dies, frame stops working | ePiframe (Google Photos), mrworf/photoframe | Local-first always. Cloud sync is additive, never required. |
| CEC commands silently fail | All CEC implementations | Log every CEC call + result. Fallback to display blanking. Retry once. |
| TV returns "unknown" power state | cec-client forum reports | Track last-sent command as assumed state. Don't block on status query. |
| SQLite degrades at scale | PhotoPrism | Index on hot columns. VACUUM on schedule. Unlikely to hit limits (<10k photos). |
| Same photos shown repeatedly | All simple shuffle implementations | Track `display_count` + `last_displayed_at`. Freshness weight prevents loops. |
| One uploader dominates display | Multi-user frames without balancing | "Equal time" setting normalizes by upload count per user. |
| libcec broken on Bookworm | Multiple Pi forum threads | Use `cec-ctl` (v4l-utils) exclusively. Do not depend on libcec. |
| Pi 5 CEC only works on HDMI-0 | Pi forum reports | Document in setup guide. Auto-detect working port via `cec-ctl -A`. |

### What No One Does (FrameCast Opportunity)

1. **Transparent rotation algorithm** — every surveyed project either uses simple random or undocumented proprietary ML. FrameCast can expose weight sliders in settings: "HOW MUCH TO FAVOR: RECENT | FAVORITES | DIVERSITY | MEMORIES" — each a 0-100 slider.

2. **Display count tracking** — no surveyed photo frame tracks how many times each photo has been displayed. This is the key input for preventing "same 10 photos" fatigue and is trivial to implement with SQLite.

3. **Per-uploader fairness** — no open-source frame balances display time across uploaders. Commercial frames don't either. This is a genuine differentiator for family use.

4. **CEC + display blanking dual-path** — most projects use one or the other. FrameCast should try CEC first (actually controls the TV), fall back to `wlr-randr` display blanking (at least saves power/prevents burn-in), and log which path succeeded.

5. **"On This Day" on a local-first frame** — Immich has it but requires a full server stack. No standalone Pi frame project implements date-based photo memories. FrameCast can do this with a single SQL query on EXIF dates.

---

## Sources

### Photo Frame Projects
- [PhotoPrism](https://github.com/photoprism/photoprism) — ~36k stars, Go + MariaDB/SQLite
- [PhotoPrism Data Models (DeepWiki)](https://deepwiki.com/photoprism/photoprism/3.3-data-models-and-entities)
- [ePiframe](https://github.com/MikeGawi/ePiframe) — 73 stars, Python + SQLite
- [MiFrame](https://github.com/tklenke/miframe) — 1 star, Python + Flask
- [mrworf/photoframe](https://github.com/mrworf/photoframe) — 237 stars, Google Photos
- [Sora Digital Photo Frame](https://github.com/Sorbh/sora-digital-photo-frame) — 72 stars, Node.js
- [FrameOS](https://github.com/FrameOS/frameos) — 426 stars, Nim + Python + TypeScript
- [simsong/picture_frame](https://github.com/simsong/picture_frame) — 2 stars, Python (early stage)

### HDMI-CEC
- [cec-client Gist (rmtsrc)](https://gist.github.com/rmtsrc/dc35cd1458cd995631a4f041ab11ff74) — comprehensive command reference
- [cec-ctl Man Page (Debian)](https://manpages.debian.org/testing/v4l-utils/cec-ctl.1.en.html)
- [python-cec](https://github.com/trainman419/python-cec) — 179 stars, C++ libcec wrapper
- [pyCEC](https://github.com/konikvranik/pyCEC) — 52 stars, TCP bridge for HA
- [Raspberry-Pi-CEC-controller](https://github.com/mkokshoorn/Raspberry-Pi-CEC-controller) — 1 star, subprocess wrapper
- [MMM-CECControl](https://github.com/nischi/MMM-CECControl) — 14 stars, MagicMirror module
- [HDMI-CEC-RaspberryPi5](https://github.com/RichFesler/HDMI-CEC-RaspberryPi5) — Pi 5 specific guide
- [Pi Forum: CEC not working on Pi 5](https://forums.raspberrypi.com/viewtopic.php?t=369097)
- [Pi Forum: Bookworm CEC breakage](https://github.com/raspberrypi/bookworm-feedback/issues/73)
- [Linux Uprising: Pi HDMI-CEC guide](https://www.linuxuprising.com/2019/07/raspberry-pi-power-on-off-tv-connected.html)

### Photo Rotation Algorithms
- [Weighted Random Algorithms (Zhanliang Liu)](https://zliu.org/post/weighted-random/) — 4 algorithms compared
- [Elitist Shuffle (Xebia)](https://xebia.com/blog/elitist-shuffle-for-recommendation-systems/)
- [Weighted Random Shuffling (Buzzvil)](https://tech.buzzvil.com/blog/weighted-random-shuffling-en/)
- [Weighted Random Algorithm (DEV Community)](https://dev.to/jacktt/understanding-the-weighted-random-algorithm-581p)
- [Recency-Weighted Scoring (Customers.ai)](https://customers.ai/recency-weighted-scoring)

### Multi-User / Photo Management
- [Photoview](https://github.com/photoview/photoview) — 6.4k stars, Go + React
- [Lychee](https://github.com/LycheeOrg/Lychee) — 4.1k stars, PHP/Laravel
- [photOS](https://github.com/avanc/photOS) — 119 stars, Buildroot + WebDAV
- [ImmichFrame](https://pixelunion.eu/blog/immichframe/) — Immich companion for frames

### Memories / "On This Day"
- [Immich Memories Discussion](https://github.com/immich-app/immich/discussions/2836)
- [Immich Memories API](https://api.immich.app/endpoints/memories)
- [Apple Photo Shuffle (TidBITS)](https://tidbits.com/2022/11/19/bring-yourself-recurring-joy-with-apples-new-lock-screen-photo-shuffle/)
- [Immich HA Memories Blueprint](https://community.home-assistant.io/t/immich-memories-blueprint/945368)
