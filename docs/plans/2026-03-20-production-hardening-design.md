# FrameCast Production Hardening v2.1 — Design

**Date:** 2026-03-20
**Base:** `bab6559` (main)
**Input:** `docs/plans/2026-03-20-12-agent-production-review.md` (100 findings)
**Scope:** All 15 critical + 40 important + trivial recommended findings (~90 total, 5-6 design-level recommended deferred)

---

## Architecture: 3-Tier Worktree Pipeline

Each tier branches from the merged result of the previous tier. Agents within a tier run in parallel on exclusive file sets.

### Tier 1: Infrastructure (3 agents, parallel)

| Agent | Files (exclusive) | Findings |
|-------|-------------------|----------|
| **pigen** | `pi-gen/*`, `requirements.txt`, `install.sh` | C10 (swap), C12 (firewall rules), I35 (bloat), I36 (pin deps), I37 (pin pi-gen commit), R: camera_auto_detect, npm ci, __pycache__ cleanup, journal Storage=volatile, watchdog max-load, Docker QEMU check, UID robustness |
| **systemd** | `systemd/*`, `app/gunicorn.conf.py` | C9 (REMOVE WatchdogSec — undo bab6559), I12 (reboot loop protection), I13 (EnvironmentFile), I14 (TimeoutStartSec on health), I38 (hostname hardening), I39 (schedule hardening), I40 (Persistent=true), R: SyslogIdentifier, CPUQuota/TasksMax, PrivateDevices, ProtectKernel*, Type=notify consideration |
| **filesystem** | `app/modules/db.py`, `app/modules/config.py`, `app/web_upload.py`, `app/modules/media.py` | C14 (atomic restore_db), C15 (disk-full delete-all), I21 (atomic Pillow writes), I23 (export ZIP tmpfs), I24 (DB restore tmpfs), R: closing() on test conn, WAL periodic checkpoint, thumbnail cap |

### Tier 2: Networking & Security (3 agents, parallel)

| Agent | Files (exclusive) | Findings |
|-------|-------------------|----------|
| **wifi** | `app/modules/wifi.py`, `app/wifi-manager.sh` (DELETE), `app/modules/services.py`, `app/modules/boot_config.py`, `app/api.py` (wifi routes only), `pi-gen/stage2-framecast/02-app/01-run-chroot.sh` (wifi-manager disable) | C1 (AP auto-start), C2 (unify — delete wifi-manager.sh), C3 (stop AP before connect), C4 (two-phase with 5s delay + TV instructions), C11 (fix _is_ap_active), I1 (captive portal via dnsmasq), I2 (timeout connects to known WiFi), I3 (WiFi settings page), I4 (test_wifi.py), I5 (onboarding_complete persistence in api.py settings map) |
| **kiosk** | `kiosk/*`, `scripts/hdmi-control.sh`, `pi-gen/stage2-framecast/01-config/files/cmdline.txt` | I6 (browser.js dynamic port), I9 (cursor hiding), I10 (display rotation), I11 (consoleblank=0 + DPMS prevention), R: cage -d (disable Xwayland), touch pointer-events:none, WAYLAND_DISPLAY export, daily kiosk restart timer |
| **security** | `app/modules/auth.py` (guest token + rate limiter), `app/api.py` (now-playing, settings/import, timezone) | I26 (guest token reject on missing key), I27 (EXIF GPS strip), I28 (now-playing localhost-only), I29 (settings/import validation), R: CSP nonce consideration, FTS5 escaping, SMART_ALBUMS comment |

### Tier 3: Application (3 agents, parallel)

| Agent | Files (exclusive) | Findings |
|-------|-------------------|----------|
| **display** | `app/frontend/src/display/*`, `app/frontend/src/lib/sse.js`, `app/sse.py` | C5 (setup→slideshow transition via wifi:connected SSE + periodic re-check), I7 (SSE pauseOnHidden:false for TV), R: duplicate /api/status fetch, Boot greeting duration use onComplete callback |
| **ota** | `app/modules/updater.py`, `scripts/update-check.sh`, `scripts/health-check.sh`, `scripts/lib/health-check-lib.sh` | C6 (commit built assets to releases OR post-update build), C7 (post-update pip install), C8 (Tags API for SHA), C13 (copy health-check to stable path before update), I15 (rollback pip install), I17 (cleanup flag on checkout failure — verify bab6559 fix), I18 (git fetch --force), I19 (stop service before checkout), I20 (disk space check), R: version comparison, failure notification file, rollback depth protection, grep -qF |
| **frontend** | `app/frontend/src/pages/*`, `app/frontend/src/components/*`, `app/frontend/src/app.jsx`, `app/frontend/src/__tests__/*` | I16 (manual rollback button in Update.jsx), I30 (fix DisplayRouter test suite), I31 (fix test assertions), I32 (Slideshow transition timeout cleanup), I33 (OfflineBanner to PhoneLayout), I34 (Update.jsx use createSSE), R: playlistFailCount reset, heartbeat cleanup, incident severity stacking, reboot confirmation, fetchWithTimeout 429 handling |

---

## Key Design Decisions

### WiFi Unification (C1-C4, C11)

**Delete `wifi-manager.sh`.** Make `wifi.py` the single AP/client lifecycle owner.

**AP auto-start:** During Flask startup in `web_upload.py`, after `_heal_env_file()` and before kiosk starts: check `wifi.is_connected()`. If false, call `wifi.start_ap()`. This ensures AP is running before Setup.jsx renders.

**AP-to-client transition (the hard problem):**
1. `POST /api/wifi/connect` receives SSID + password
2. API responds immediately with `{status: "connecting", ssid: "..."}`
3. SSE broadcasts `wifi:connecting` event (TV shows transition instructions)
4. 5-second timer fires: `wifi.stop_ap()` then `wifi.connect(ssid, password)`
5. On success: SSE broadcasts `wifi:connected` (TV transitions from setup)
6. On failure: `wifi.start_ap()` again, SSE broadcasts `wifi:failed`
7. TV shows reconnection instructions: "CONNECT YOUR PHONE TO [SSID]. OPEN [hostname].local:8080"
8. Phone: pre-disconnect message shown before AP stops. After reconnecting to home WiFi, user opens `.local` URL (avahi mDNS).

**Captive portal:** Configure dnsmasq in AP mode with `address=/#/192.168.4.1` to redirect all DNS queries to the Pi. This triggers iOS/Android captive portal detection, auto-opening the setup page.

### OTA Pipeline (C6-C8, C13)

**Frontend asset delivery:** Add a `scripts/post-update.sh` that runs after `git checkout`:
1. `pip3 install --break-system-packages -q -r requirements.txt`
2. If `package.json` changed: `cd app/frontend && npm ci && npm run build`
3. If `app/modules/db.py` changed: Flask will auto-migrate on next startup
4. Copy current `health-check.sh` to `/var/lib/framecast/health-check-stable.sh` BEFORE checkout
5. `systemctl restart framecast`

**SHA verification:** Replace `target_commitish` usage with GitHub Tags API: `GET /repos/{owner}/{repo}/git/refs/tags/{tag}` → extract `object.sha`. Dereference annotated tags with `^{}`.

**Health check safety:** `framecast-health.service` ExecStart points to `/var/lib/framecast/health-check-stable.sh` (copied before update), not the checked-out version.

### Display State Machine (C5)

**New SSE events:** `wifi:connected`, `wifi:connecting`, `wifi:failed`

**DisplayRouter changes:**
- Listen for `wifi:connected` → re-fetch `/api/status` → route to welcome/slideshow
- Listen for `wifi:connecting` → show transition screen with instructions
- Add periodic status re-check every 60s when in "setup" state (fallback if SSE missed)
- `photo:added` handler: transition from BOTH "welcome" AND "setup" → "slideshow"

### Disk-Full Recovery (C15)

**Reorder delete-all:** Attempt `filepath.unlink()` on files first (frees space), then update DB. If DB update fails after files are deleted, the orphan cleanup timer will reconcile. User recovers from disk full immediately.

**Single delete:** Same reorder — unlink first, DB update second.

### Test Strategy

- Every agent runs `make test-all` before committing (365 existing tests must pass)
- Frontend agent fixes 6 broken DisplayRouter tests + corrects assertions
- WiFi agent creates `test_wifi.py` (AP lifecycle, connect flow, timeout, captive portal mock)
- Each agent runs `make typecheck` (mypy strict)

---

## Deferred (not in scope)

- Issue #2: Read-only overlay FS (needs hardware testing)
- Issue #10: Video HW decode (needs Pi + GTK-WebKit)
- Issue #28: PIR motion sensor (needs hardware)
- R: Update channels / pre-release support (design-level)
- R: Incident severity stacking (design-level)
- I22: Read-only overlay FS (same as #2)
- I25: Move DB to separate partition (requires migration tooling)
