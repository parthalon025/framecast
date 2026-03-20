# FrameCast

Turn any TV into a family photo frame — flash an SD card, boot the Pi, done. Browser-based slideshow with CSS transitions, superhot-ui terminal interface, WiFi captive portal, OTA updates.

## Stack

- Python (Flask + gunicorn), SSE for real-time updates
- SQLite (WAL mode) for content metadata
- Preact + esbuild + superhot-ui (green phosphor monitor variant)
- Wayland kiosk (cage + GTK-WebKit, no X11)
- NetworkManager (nmcli) for WiFi provisioning
- pi-gen for OS image builds
- GitHub Actions CI/CD

## Architecture

One Flask app serves two surfaces:
- **Phone** → upload, albums, settings, map, stats, onboarding (Preact SPA at `/`, 4 nav tabs)
- **TV** → slideshow with CSS transitions, boot sequence, QR codes (kiosk browser at `/display`)

**Route architecture:** `api.py` blueprint is the single source of truth for all `/api/*` endpoints (~70 routes). `web_upload.py` is a thin app factory + upload/delete handlers + static file serving. All routes return JSON only — no dual-mode HTML/JSON responses.

Data layer: SQLite DB (`framecast.db`) with photos, albums, tags, users, display_stats tables. WAL mode + busy_timeout for concurrent access. Stats buffered in memory, flushed every 5 minutes (SD card protection).

Slideshow: server computes weighted 50-photo playlist, client plays locally. Weighted by recency, favorites (3x), diversity. "On This Day" memories from EXIF dates.

## Key Directories

| Path | Purpose |
|------|---------|
| `app/` | Flask web app (routes, modules, templates) |
| `app/frontend/src/` | Preact + superhot-ui JSX source |
| `app/frontend/src/styles/` | CSS architecture (8 files: tokens, base, slideshow, display, photos, settings, responsive, motion) |
| `app/frontend/src/lib/` | Shared JS utilities (sse.js, fetch.js, format.js, toast.js, incident.js) |
| `app/frontend/src/components/` | Reusable components (PhotoCard, Lightbox, PinGate, ShDropzone, PhoneLayout, OfflineBanner) |
| `app/frontend/src/pages/` | Page components (Upload, Albums, Settings, Map, Stats, Users, Onboard, Update) |
| `app/frontend/src/display/` | TV display components (Slideshow, DisplayRouter, Boot, Setup, Welcome) |
| `app/modules/` | Python modules (db, rotation, users, cec, auth, config, media, wifi, updater, services, rate_limiter, boot_config) |
| `kiosk/` | GJS/WebKit browser + cage launcher |
| `pi-gen/` | Custom pi-gen stage for OS image build |
| `systemd/` | Service and timer definitions |
| `scripts/` | Health check, HDMI control, smoke tests |
| `tests/` | pytest suites (test_db, test_rotation, test_users, test_cec, test_albums, test_auth, test_rate_limiter, test_config) |
| `docs/plans/` | Design docs, implementation plans, research |

## Python Modules

| Module | Purpose |
|--------|---------|
| `db.py` | SQLite content model. WAL, closing(), public API (get_playlist_candidates, unquarantine_photo, compute_sha256, prune_quarantined, bulk_quarantine_all, create_user_returning_row, delete_user_reassign), stats buffering, migration. |
| `rotation.py` | Weighted slideshow playlist. Binary CDF search, "On This Day", recency/favorite/diversity weighting. |
| `users.py` | Multi-user management. Cookie-based identity, upload attribution, stats aggregation. |
| `cec.py` | HDMI-CEC via `cec-ctl` (v4l-utils). TV power, standby, status, active source. NOT cec-client (broken on Bookworm). |
| `rate_limiter.py` | Shared rate limiter class. Used by API (60/min POST) and PIN auth (5 attempts/4-digit, 3/6-digit). |
| `auth.py` | PIN authentication. HMAC-SHA256 tokens, SameSite=Strict, Origin validation, configurable 4/6-digit. |
| `config.py` | .env config management. Atomic writes with fsync. |
| `media.py` | Image/video processing. EXIF, GPS, thumbnails, format_size. |
| `wifi.py` | WiFi provisioning via nmcli. Scan, connect, AP mode with 30-min auto-timeout. |
| `updater.py` | OTA updates. GitHub Releases API, SHA256 verification, HMAC-signed rollback tags. |

## Services

| Service | Purpose |
|---------|---------|
| `framecast` | gunicorn + Flask (WatchdogSec=120, MemoryMax=512M, ProtectSystem=strict) |
| `framecast-kiosk` | cage + GTK-WebKit (Requires=framecast, WatchdogSec=60) |
| `wifi-manager` | NetworkManager WiFi provisioning |
| `framecast-update.timer` | OTA update checker (daily, opt-in) |
| `framecast-health.timer` | Health-check rollback (90s after boot) |
| `framecast-schedule.timer` | HDMI-CEC display schedule (every minute) |

## Build

- Frontend: `cd app/frontend && npm install && npm run build`
- Dev: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`
- Tests (Python): `make pytest` (~330 tests — unit, property, concurrency, fault injection, contracts, benchmarks)
- Tests (Frontend): `make test-frontend` (vitest — SSE client tests)
- Tests (Shell): `make test-shell` (bats — health-check rollback logic)
- Tests (All): `make test-all` (runs Python + frontend + shell)
- Type check: `make typecheck` (mypy strict on modules + sse)
- Benchmarks: `make benchmark` (Pi 3 regression thresholds)
- Mutation: `make mutate` (on-demand test quality audit)
- Image (full): `cd pi-gen && ./build.sh` (native, ~30-40min first time)
- Image (base only): `cd pi-gen && ./build.sh --base-only` (OS without app)
- Image (add app): `cd pi-gen && ./build.sh --continue` (~5min, reuses cached rootfs)
- Image (iterate): `cd pi-gen && ./build.sh --app-only` (~3min, fastest — rebuilds only 02-app)
- Image (Docker): `cd pi-gen && ./build.sh --docker`
- Pi-gen branch: `bookworm-arm64`. Frontend builds on host (native x86), not QEMU chroot.

## Conventions

- Target: Raspberry Pi 3/4/5 (arm64, Bookworm)
- **Gunicorn: workers=1 MANDATORY** — SSE, CEC, stats buffer are process-singletons (Lesson #1356)
- All SQLite: `contextlib.closing()` + WAL + `busy_timeout=5000` (Lesson #34, #1335)
- All file writes: atomic (tmp + fsync + rename) (Lesson #1234)
- All `except` blocks: log before returning fallback (Lesson #1418)
- All subprocess `kill()`/`terminate()`: `suppress(ProcessLookupError)` (Lesson #81)
- Toggle operations: atomic SQL `UPDATE SET x = NOT x` (Lesson #1274)
- DB INSERT before file write, not after (Lesson #1670)
- NEVER use `h` as a callback parameter name in JSX (esbuild shadows, Lesson #13)
- Frontend: superhot-ui green phosphor variant, piOS voice (STANDBY, FAULT, COMPLETE, RESTORED)
- 24-hour time, ISO dates, abbreviated units (s, m, h, d)
- CSS: 8 focused files in `styles/`, no `@import` (concatenated at build time)
- Navigation: 4 bottom tabs (Upload, Albums, Map, Settings). Stats/System are Settings subsections.
- Photos in grid: `/thumbnail/` with `/media/` fallback + `loading="lazy"`
- DB public API only — never reach into `_write_lock` directly from routes; use the named functions in `db.py`
- `createSSE` helper (sse.js) used on both Phone SPA and TV DisplayRouter — handles exponential backoff and page-background pause
- TV display uses superhot-ui atmosphere: facility state (normal/alert), narrator (GLaDOS/Wheatley), ShAnnouncement for boot/setup/welcome
- Boot is keyboard-free: masked getty, kiosk service with TTYPath, quiet kernel, hidden cursor

## Design Docs

- `docs/plans/2026-03-19-framecast-image-design.md` — v2.0 design document
- `docs/plans/2026-03-19-framecast-v2-polish-design.md` — v2.1 polish design (gap analysis + 8-phase plan)
- `docs/plans/2026-03-19-framecast-v2-polish-plan.md` — v2.1 implementation plan (72 tasks, 8 batches)
- `docs/plans/2026-03-19-v2-polish-research.md` — Competitive research (PhotoPrism, Immich, CEC, rotation algorithms)
- `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md` — Pi-gen kiosk research
- `docs/plans/2026-03-19-mpv-vs-vlc-display-stack-research.md` — Display stack research
