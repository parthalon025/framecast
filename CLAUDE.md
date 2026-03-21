# FrameCast

Turn any TV into a family photo frame — flash an SD card, boot the Pi, done. Browser-based slideshow with CSS transitions, superhot-ui terminal interface, WiFi captive portal, OTA updates.

## Project Status: FEATURE FREEZE (v2.1.0)

**No new features.** Only bug fixes, security patches, build fixes, and documentation updates. If a change adds new user-facing behavior, it requires explicit approval. This includes new API endpoints, UI pages, config options, and pi-gen stages.

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
| `app/modules/` | Python modules (db, rotation, users, cec, auth, config, media, wifi, updater, services, rate_limiter, boot_config — 12 modules) |
| `kiosk/` | GJS/WebKit browser + cage launcher |
| `pi-gen/` | Custom pi-gen stage for OS image build |
| `systemd/` | Service and timer definitions |
| `scripts/` | Health check, HDMI control, OTA post-update, WiFi check, smoke test, cert generation, lib/ |
| `app/templates/` | Single template: `spa.html` (SPA shell for both phone + TV) |
| `tests/` | pytest suites (test_db, test_rotation, test_users, test_cec, test_albums, test_auth, test_rate_limiter, test_config, test_api_integration) |
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
| `services.py` | System service management (restart, reboot, shutdown via sudo). |
| `boot_config.py` | Boot configuration (SSH toggle, boot config.txt settings). |

## Services

| Service | Purpose |
|---------|---------|
| `framecast` | gunicorn + Flask (MemoryMax=512M, ProtectSystem=strict) |
| `framecast-kiosk` | cage + GTK-WebKit (BindsTo=framecast, MemoryMax=512M) |
| `wifi-manager` | Boot-time WiFi connectivity check (oneshot) |
| `framecast-hostname` | First-boot unique hostname from MAC address (oneshot, runs once) |
| `framecast-update.timer` | OTA update checker (daily, opt-in) |
| `framecast-health.timer` | Post-update health check with HMAC-validated rollback (90s after boot) |
| `framecast-schedule.timer` | HDMI-CEC display schedule (every minute) |

## Build

- Frontend: `cd app/frontend && npm install && npm run build`
- Dev: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`
- Tests (Python): `make pytest` (363 tests — unit, property, concurrency, fault injection, contracts, benchmarks)
- Tests (Frontend): `make test-frontend` (vitest — SSE client tests)
- Tests (Shell): `make test-shell` (bats — health-check rollback logic)
- Tests (All): `make test-all` (runs Python + frontend + shell)
- Type check: `make typecheck` (mypy strict on modules + sse)
- Benchmarks: `make benchmark` (Pi 3 regression thresholds)
- Mutation: `make mutate` (on-demand test quality audit)
- Image build decision tree:
  - First time? → `cd pi-gen && ./build.sh` (native, ~30-40min)
  - Iterating app only? → `cd pi-gen && ./build.sh --app-only` (~3min, fastest)
  - No Docker? OS first, then app: `./build.sh --base-only` then `./build.sh --continue`
  - On Windows? → `cd pi-gen && ./build.sh --docker`
- Pi-gen branch: `bookworm-arm64`. Frontend builds on host (native x86), not QEMU chroot.

## CI/CD Pipeline

**PR gate (16 jobs):** lint-python, shellcheck, typecheck, pytest, integration (gunicorn + real endpoints), build-frontend, vitest, bats, architecture fitness, smoke, Claude Code Review, Claude Security Review (path-triggered), actionlint, commitlint, CodeQL (SAST), gitleaks. All gated through `CI Pass` required status check.

**Architecture fitness checks:** no duplicate NM connection owners, no stale v1 naming (PiPhotoFrame), WatchdogSec requires Type=notify, bare except blocks must log.

**Release pipeline (v* tag):** test gate → pi-gen build → QEMU arm64 boot test → SBOM (CycloneDX) → cosign keyless signing → SLSA attestation → GitHub Release → Telegram notification.

**Automation:** release-please (auto VERSION + CHANGELOG from conventional commits), Dependabot (weekly pip/npm, monthly Actions), branch protection (CI Pass required, enforce admins, linear history, squash-only), commitlint (conventional commit enforcement).

**AI review:** `anthropics/claude-code-action@v1` reads CLAUDE.md conventions. Security review path-triggered on auth.py, wifi.py, updater.py, api.py, web_upload.py, scripts/, pi-gen/.

**Repo secrets:** `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

**Supply chain:** SHA-pinned actions, cosign signatures, SLSA provenance attestations, CycloneDX SBOMs, pip-audit + npm audit, gitleaks, CodeQL.

**Config files:** `.release-please-manifest.json`, `release-please-config.json`, `.github/dependabot.yml`, `.github/CODEOWNERS`, `.commitlintrc.yml`, `.pre-commit-config.yaml`.

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

## Frontend Infrastructure

- **Centralized toast:** `lib/toast.js` — signal-based, single stack rendered in PhoneLayout. Import `showToast(message, type, duration)` from any page.
- **Incident state:** `lib/incident.js` — signal-based device-level alerts. `raiseIncident(message, severity)` / `clearIncident()`.
- **Heartbeat:** `app.jsx` — 30s polling to `/api/status`. After 3 failures: raises incident, sets facility `alert`. On recovery: clears incident, triggers `recoverySequence`.
- **superhot-ui components used (19):** ShNav, ShModal, ShToast, ShFrozen, ShSkeleton, ShCollapsible, ShDataTable, ShPageBanner, ShStatusBadge, ShErrorState, ShEmptyState, ShMantra, ShIncidentHUD, ShHeroCard, ShTimeChart, ShThreatPulse, ShDropzone (custom), ShAnnouncement, ShNarrator.

## Design Docs

- `docs/plans/2026-03-19-framecast-image-design.md` — v2.0 design document
- `docs/plans/2026-03-19-framecast-v2-polish-design.md` — v2.1 polish design (gap analysis + 8-phase plan)
- `docs/plans/2026-03-19-framecast-v2-polish-plan.md` — v2.1 implementation plan (72 tasks, 8 batches)
- `docs/plans/2026-03-20-api-ui-integration-design.md` — API consolidation + superhot-ui maximization design
- `docs/plans/2026-03-20-api-ui-superhot-plan.md` — API consolidation implementation plan (12 batches)
- `docs/plans/2026-03-19-v2-polish-research.md` — Competitive research (PhotoPrism, Immich, CEC, rotation algorithms)
- `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md` — Pi-gen kiosk research
- `docs/plans/2026-03-19-mpv-vs-vlc-display-stack-research.md` — Display stack research
