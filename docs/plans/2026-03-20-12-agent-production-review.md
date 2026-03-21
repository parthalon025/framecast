# FrameCast 12-Agent Production Readiness Review

**Date:** 2026-03-20
**Scope:** Full chain — pi-gen image build → boot → WiFi provisioning → OTA updates → rollback
**Method:** 10 domain agents + 2 integration agents (horizontal sweep + vertical trace)
**Agents:** pi-gen, boot, wifi, systemd, ota, health-check, kiosk, filesystem, security, frontend, horizontal, vertical

---

## Executive Summary

FrameCast has **strong fundamentals** — atomic writes, parameterized SQL, rate-limited auth, SSE with backoff, 365 tests across 11 layers. The security posture is solid for a LAN appliance. The individual components are well-built.

**The problems are at the seams.** The vertical trace agent found 4 critical Cluster B bugs where each layer passes its own test but the handoff fails. The WiFi provisioning system has two competing implementations that were never unified. The OTA pipeline can only safely deliver Python source-only changes with no new dependencies and no frontend changes.

**Verdict:** Not production-ready. ~15 critical findings block shipping. The WiFi onboarding flow, OTA update pipeline, and display state machine need architectural fixes, not patches.

---

## Findings by Severity

### CRITICAL — Blocks Production (15 findings)

#### First-Boot Onboarding (broken end-to-end)

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C1** | **AP never auto-starts on first boot.** Nothing starts the AP hotspot when the Pi boots with no WiFi configured. TV displays "Connect to FrameCast-XXXX" but the AP isn't running. First-boot onboarding is unreachable without SSH or `framecast-wifi.txt` on boot partition. | vertical, wifi | `wifi.py`, `wifi-manager.sh` |
| **C2** | **Two competing AP systems fight each other.** `wifi-manager.sh` creates `PiPhotoFrame-AP` with WPA-PSK password `photoframe`. `wifi.py` creates `FrameCast-XXXX` with no password. Different NM connection profiles — one can't stop the other. | wifi | `wifi-manager.sh:23`, `wifi.py:288-298` |
| **C3** | **`wifi.connect()` fails 100% in AP mode.** Calls `nmcli dev wifi connect` while hotspot is active on `wlan0`. NM can't do both on one interface. | wifi | `wifi.py:179-202` |
| **C4** | **AP-to-client transition disconnects the phone.** Stopping AP to connect to WiFi drops the phone's connection to the Pi. HTTP response from `/api/wifi/connect` never arrives. No reconnection logic, no mDNS discovery. | wifi, vertical | `wifi.py`, `Onboard.jsx` |
| **C5** | **TV stuck on Setup screen after WiFi connects.** DisplayRouter checks WiFi once during boot. No SSE event for WiFi state change, no periodic re-check. `photo:added` handler only transitions from "welcome" → "slideshow", not "setup" → anything. TV stays on Setup until reboot. | vertical | `DisplayRouter.jsx:63-89,119-125` |

#### OTA Update Pipeline (fundamentally narrow)

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C6** | **Frontend assets not in git — OTA deletes UI.** `git checkout <tag>` will delete pre-built JS/CSS in `app/static/`. pi-gen builds frontend during image creation; tagged releases don't include build artifacts. OTA updates that change any frontend code leave UI non-functional. | ota | `pi-gen/02-app/01-run.sh:27-29` |
| **C7** | **No post-update pip install / rebuild / migration.** `git checkout` is the entire update. New Python deps = `ImportError`. Changed frontend = no effect. Schema change = crash. | ota, health | `updater.py:248-262` |
| **C8** | **`target_commitish` is a branch name, not a SHA.** GitHub Releases API returns `"main"` not a commit hash. SHA verification compares against the string `"main"`, causing false mismatch → update aborted. Or if it passes through, verification is meaningless. | ota | `updater.py:62-65,90,99` |

#### Watchdog & Memory

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C9** | **WatchdogSec=120 is inert (3 agents confirmed).** `Type=simple` with no `sd_notify` signaling. Systemd silently ignores WatchdogSec. Flask deadlocks go undetected. False sense of safety. Kiosk agent notes it may actually *kill* Flask every 2min depending on systemd version behavior. | systemd, boot, kiosk | `framecast.service:10,14` |
| **C10** | **No swap on Pi 3 — OOM guaranteed.** MemoryMax=512M on each of 2 services = 1024M on 1GB device. WebKit's child `WebProcess` isn't capped by cgroup. OOM killer fires randomly. | kiosk | `pi-gen/03-system/01-run.sh` |

#### Security

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C11** | **WiFi API auth permanently bypassed.** `_is_ap_active()` checks `wifi-manager.service` which is always "active" (RemainAfterExit=yes). All `/api/wifi/*` routes skip PIN auth at all times, not just during AP mode. | wifi, vertical, security | `auth.py:96-104,121` |
| **C12** | **Firewall rules never applied.** `ufw-setup.sh` installed but never called. ufw enabled with default-permissive rules. Port 8080 open to all networks. | pi-gen | `pi-gen/03-system/01-run.sh:26`, `02-app/01-run-chroot.sh:106-109` |

#### Health Check Self-Healing

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C13** | **Broken health-check.sh in new version = no rollback.** Health check runs from `/opt/framecast/scripts/health-check.sh` which is part of the checked-out code. Bug in new version's script kills the safety net. | health | `framecast-health.service:8` |

#### Data Integrity

| # | Finding | Source Agent(s) | File(s) |
|---|---------|-----------------|---------|
| **C14** | **`restore_db()` uses non-atomic `shutil.copy2`.** Power loss mid-copy truncates `framecast.db`. Unrecoverable. | filesystem | `db.py:1115` |
| **C15** | **Disk full prevents `delete-all` — user stuck.** DB UPDATE (quarantine) fails before any files are unlinked. User cannot free space through UI. Only recovery: SSH or pull SD card. | vertical | `web_upload.py:659-664` |

---

### IMPORTANT — Fix Before Shipping (34 findings)

#### WiFi & Onboarding

| # | Finding | Agent | File |
|---|---------|-------|------|
| I1 | No captive portal redirect — phone shows "no internet", may auto-disconnect (iOS) | wifi | design gap |
| I2 | AP auto-timeout cycles AP instead of connecting to known WiFi | wifi | `wifi.py:231-250` |
| I3 | No post-setup WiFi management in Settings (read-only) | wifi | `Settings.jsx:711-729` |
| I4 | No WiFi test coverage (`test_wifi.py` missing) | wifi | `tests/` |
| I5 | `onboarding_complete` key silently ignored — wizard re-runs every time | vertical | `api.py:149-167` |

#### Boot & Kiosk

| # | Finding | Agent | File |
|---|---------|-------|------|
| I6 | `browser.js` hardcodes port 8080, ignores `WEB_PORT` | boot, horizontal | `browser.js:11` |
| I7 | SSE visibility-change disconnects TV display (shared code with phone) | boot | `sse.js:63-77` |
| I8 | `install.sh` is stale v1 code (VLC/X11 stack) — will produce broken install | boot, horizontal | `install.sh` |
| I9 | Mouse cursor visible under Wayland (no CSS `cursor:none`, no compositor config) | kiosk | `browser.js`, `display.css` |
| I10 | No display rotation for portrait-mounted frames | kiosk | `kiosk.sh` |
| I11 | No DPMS/blanking prevention under Wayland (screen may blank after 10min) | kiosk | `kiosk.sh`, `cmdline.txt` |
| I12 | `StartLimitAction=reboot` on both services — broken Flask = infinite reboot loop | boot, systemd, kiosk | `framecast.service:7`, `framecast-kiosk.service:7` |
| I13 | Missing `EnvironmentFile` in `framecast.service` | boot | `framecast.service` |

#### OTA & Health Check

| # | Finding | Agent | File |
|---|---------|-------|------|
| I14 | No `TimeoutStartSec` on health-check service — hangs forever if curl/git blocks | health | `framecast-health.service` |
| I15 | Rollback doesn't reinstall pip deps — old version may crash on missing imports | health | `health-check.sh:121-128` |
| I16 | No manual rollback from phone UI | health | `Update.jsx` |
| I17 | `update-in-progress` flag not cleaned on checkout failure — false rollback on next boot | vertical, ota | `updater.py:249-251` |
| I18 | `git fetch --tags` doesn't force-update existing tags (stale tag reuse) | ota | `updater.py:235` |
| I19 | `git checkout` during live operation is non-atomic (mixed file state) | ota | `updater.py:248-251` |
| I20 | No disk space check before git fetch/checkout | ota | `updater.py` |

#### Filesystem & Data

| # | Finding | Agent | File |
|---|---------|-------|------|
| I21 | `fix_orientation()` and `_auto_resize_image()` write non-atomically (Pillow `.save()`) | filesystem | `media.py:211`, `web_upload.py:389` |
| I22 | No read-only overlay FS (issue #2 open) — power-pull risks ext4 corruption | filesystem | pi-gen |
| I23 | Export ZIP targets 100MB tmpfs — fails for users with >100MB photos | filesystem | `api.py:979` |
| I24 | DB restore temp file also targets 100MB tmpfs | filesystem | `api.py:923` |
| I25 | SQLite DB on same partition as media — disk full corrupts DB operations | vertical | `db.py:157` |

#### Security

| # | Finding | Agent | File |
|---|---------|-------|------|
| I26 | Guest token uses hardcoded `"insecure-fallback"` secret when key unset | security | `auth.py:176-178` |
| I27 | EXIF GPS data preserved on served images — location leakage | security | `media.py:179-216` |
| I28 | `/api/slideshow/now-playing` POST unauthenticated | security, horizontal | `api.py:744` |
| I29 | `/api/settings/import` bypasses value validation | horizontal | `api.py:380-398` |

#### Frontend

| # | Finding | Agent | File |
|---|---------|-------|------|
| I30 | DisplayRouter test suite broken — 6/6 tests fail (missing mock) | frontend | `displayRouter.test.js:11` |
| I31 | Test assertions contradict code behavior (2 cases) | frontend | `displayRouter.test.js:75-89,142-150` |
| I32 | Slideshow transition timeout fires after unmount — null ref crash | frontend | `Slideshow.jsx:335-362` |
| I33 | `OfflineBanner` only on Upload page, not global | frontend | `Upload.jsx:531` |
| I34 | Update page uses raw `EventSource` — no reconnect during server restart | frontend | `Update.jsx:64-81` |

#### Image Build

| # | Finding | Agent | File |
|---|---------|-------|------|
| I35 | ~200MB bloat: nodejs, npm, python3-pip shipped at runtime (unused) | pi-gen | `00-packages:13-15` |
| I36 | Python deps floor-pinned not exact-pinned (non-reproducible builds) | pi-gen | `requirements.txt` |
| I37 | pi-gen cloned at HEAD, not pinned commit (non-reproducible base) | pi-gen | `build.sh:43-47` |

#### systemd Hardening

| # | Finding | Agent | File |
|---|---------|-------|------|
| I38 | `framecast-hostname.service` runs as root with zero hardening | systemd | `framecast-hostname.service` |
| I39 | `framecast-schedule.service` runs as root with no hardening | systemd | `framecast-schedule.service` |
| I40 | No `Persistent=true` on schedule timer | systemd | `framecast-schedule.timer` |

---

### RECOMMENDED — Nice to Have (45 findings)

Grouped by area, lower priority. Full details in individual agent reports.

**Image Build (7):** `__pycache__` cleanup, watchdog `max-load-1` threshold too high (24), npm should use `npm ci`, Docker build QEMU pre-check, hardcoded UID 1000, `camera_auto_detect=1` loads unnecessary firmware, journal should be `Storage=volatile`.

**systemd (8):** `SyslogIdentifier` missing on all services, no `CPUQuota`/`TasksMax`, `PrivateDevices=true` missing on non-hardware services, `ProtectKernelTunables`/`ProtectKernelModules` missing, kiosk hardcoded `XDG_RUNTIME_DIR=/run/user/1000`, `gunicorn.conf.py` timeout=120 is high with workers=1, consider `Type=notify` for startup sequencing.

**Kiosk (6):** Launch cage with `-d` (disable Xwayland, saves ~20MB), touch input `pointer-events:none`, multi-display documentation, WebKit process cache grows unbounded (add daily restart), `WAYLAND_DISPLAY` not exported for schedule timer, CLAUDE.md doc drift.

**Security (5):** CSP `unsafe-inline`, FTS5 query escaping, SQL construction comments, in-memory rate limiter resets on restart, systemd hardening could go further.

**Frontend (8):** Duplicate `/api/status` fetch during boot, module-level `playlistFailCount` persists across mount cycles, heartbeat interval no cleanup (HMR stacks), QR code hardcodes AP IP, Setup WiFi retry limited to 1, incident.js drops lower-severity incidents, AmbientClock re-renders every second on Pi 3, reboot button has no confirmation.

**WiFi (6):** Colon escaping in SSID scan is fragile, AP marker file on persistent storage (should be tmpfs), `/api/wifi/test` pings 8.8.8.8 (fails behind DNS-only firewalls), boot partition WiFi password in plaintext, TV doesn't detect WiFi recovery from Setup, nmcli rescan is async with fixed sleep.

**OTA/Health (7):** Version comparison fallback to string is unreliable, no failure notification channel to user, rollback to `main` branch is risky (untested HEAD), auto-update timer runs even when disabled (benign), no update channel/pre-release support, health check doesn't verify DB accessibility, bats tests only cover lib functions not full flow.

**Filesystem (4):** Thumbnail cache unbounded by count, periodic WAL checkpoint (currently only at shutdown), `closing()` missing on test connection in `restore_db`, `wifi.py` AP marker write is non-atomic.

**Vertical Trace (2):** Failed `unquarantine_photo()` leaves orphaned files, TV WiFi-loss detection delayed up to 8 minutes.

---

## Cross-Cutting Themes

### Theme 1: v1 → v2 Migration Incomplete

The WiFi provisioning has two systems (`wifi-manager.sh` = v1, `wifi.py` = v2). `install.sh` is v1 dead code. Some naming uses `PiPhotoFrame` (v1) while others use `FrameCast` (v2). The AP profile names don't match. This creates real bugs, not just cosmetic issues.

**Action:** Unify WiFi provisioning into a single system. Delete or rename stale v1 artifacts.

### Theme 2: OTA Pipeline is Structurally Narrow

The git-based OTA can only safely deliver Python source changes with no new deps and no frontend changes. This covers maybe 20% of realistic updates. Frontend changes, new dependencies, schema migrations, and systemd unit changes all break.

**Action:** Either (a) commit built frontend assets to tagged releases + add post-update pip/migrate script, or (b) switch to tarball-based OTA with a proper update manifest.

### Theme 3: Display State Machine Has No Feedback Path

The TV display checks WiFi/photo status once during boot, then relies on a narrow set of SSE events. No event for WiFi state change, no periodic re-check, no mechanism to transition from "setup" to other states without reboot.

**Action:** Add periodic status polling or SSE events for WiFi/system state changes. DisplayRouter needs a `wifi:connected` event handler.

### Theme 4: Disk Full is a Trap

The SQLite DB shares the same partition as media. When full, DB writes fail, which blocks the `delete-all` flow (must UPDATE before DELETE), trapping the user. Export and restore also target the 100MB tmpfs.

**Action:** Move DB to `/var/lib/framecast/` (separate from media). Make delete-all attempt file unlinks before DB writes. Route temp files to media dir, not tmpfs.

### Theme 5: Watchdog/Restart/Reboot Cascade Risk

Inert WatchdogSec + StartLimitAction=reboot on both services + no swap on Pi 3 = multiple paths to infinite reboot loop with no SSH access (disabled by default).

**Action:** Remove WatchdogSec or implement sd_notify properly. Change kiosk StartLimitAction to none. Add swap. Add a reboot-loop counter that stops after 3 cycles.

---

## Prioritized Fix Order

### Phase 1: Ship-Blockers (must fix)

1. **Unify WiFi system** — delete `wifi-manager.sh`, make `wifi.py` the single owner. Auto-start AP on boot when no WiFi configured.
2. **Fix display state machine** — add `wifi:connected` SSE event, DisplayRouter handles setup→welcome/slideshow transition.
3. **Fix auth bypass** — `_is_ap_active()` should check actual AP state, not systemd service.
4. **Fix WatchdogSec** — remove from `framecast.service` (rely on health timer).
5. **Fix OTA frontend delivery** — commit built assets to tagged releases OR add post-update build step.
6. **Fix OTA post-update deps** — add `pip install -r requirements.txt` after checkout.
7. **Apply firewall rules** — call `ufw-setup.sh` from chroot script.
8. **Fix `restore_db()` atomic write** — use tmp+fsync+rename pattern.
9. **Fix disk-full delete path** — attempt file unlink before DB quarantine write.
10. **Add swap for Pi 3** — even 256MB prevents OOM kills.

### Phase 2: Important (before shipping to users)

11. Fix `browser.js` hardcoded port
12. Fix Setup.jsx hardcoded AP URL
13. Add captive portal redirect (dnsmasq or hostapd redirect)
14. Fix Slideshow transition timeout cleanup
15. Fix DisplayRouter test suite
16. Move OfflineBanner to PhoneLayout (global)
17. Add `TimeoutStartSec` to health-check service
18. Copy health-check.sh to stable location before updates
19. Add `consoleblank=0` to cmdline.txt (prevent DPMS)
20. Add cursor hiding (CSS + Wayland)
21. Remove nodejs/npm/python3-pip from runtime image
22. Pin pi-gen commit hash
23. Pin Python dependency versions

### Phase 3: Hardening (production polish)

24. Add display rotation setting
25. Add manual rollback button in Update page
26. Add disk-low SSE alerts (85%, 90%)
27. Move DB to `/var/lib/framecast/`
28. Add reboot-loop counter
29. Harden remaining systemd services
30. Strip EXIF GPS from served images
31. Fix guest token fallback secret
32. Add WiFi management to Settings page
33. Journal to `Storage=volatile`

---

## What Works Well

- **Auth system:** HMAC-SHA256 tokens, SameSite=Strict, rate-limited PIN, Origin validation — well-designed
- **Atomic writes in config.py:** textbook tmp+fsync+rename
- **Upload pipeline:** DB-insert-before-file-write, quarantine pattern, per-file disk check, semaphore concurrency control
- **SSE infrastructure:** Max clients, keepalive, stale detection, ring buffer, exponential backoff
- **Keyboard-free boot:** 6-layer suppression (kernel, getty mask, userconfig mask, debconf, raspi-config, passwd lock)
- **Testing depth:** 365 tests across 11 layers, including property-based, concurrency stress, fault injection, and SSE contract schemas
- **Boot partition WiFi provisioning:** Solid power-user alternative to AP mode
- **External dependency handling:** Every subprocess call has timeout, error handling, and graceful degradation
- **SQL injection:** Zero instances found — all user-facing queries use parameterization

---

*Generated by 12 parallel review agents. Individual agent transcripts at `/tmp/claude-1000/-home-justin-Documents/c8622ae9-cad7-45dd-8b61-070b691b5db0/tasks/`.*
