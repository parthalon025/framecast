# FrameCast Production Readiness Plan

**Date:** 2026-03-28
**Current:** v2.2.1 (released 2026-03-29, SD card audit fixes)
**Scope:** Bug fixes and reliability hardening only (feature freeze enforced)
**Source:** 36-finding gap analysis from full codebase audit

## Status: FEATURE FREEZE

All items below are **bug fixes, reliability hardening, or security patches** — no new user-facing features. Each batch is a single PR. Batches are ordered by severity and dependency.

---

## Phase 1: Boot & Survive (Critical — Pi must boot and stay up)

### Batch 1A: Infinite Reboot Trap + Health Check Path
**Risk:** Pi enters infinite reboot loop with no SSH recovery
**Effort:** 1h | **Files:** 3

| # | Fix | File |
|---|-----|------|
| 1 | Change `StartLimitAction=reboot` → `StartLimitAction=none` | `systemd/framecast.service` |
| 2 | Point `ExecStart` to `/var/lib/framecast/health-check-stable.sh` (the pre-checkout copy) | `systemd/framecast-health.service` |
| 3 | Clean up `update-in-progress` flag on checkout failure (missing `_cleanup_update_flag()` call) | `app/modules/updater.py` |

### Batch 1B: Partition Resize in Build Pipeline
**Risk:** Root partition stuck at 3.1GB on 128GB card
**Effort:** 30m | **Files:** 1 | **PR:** #132 (already open)

| # | Fix | File |
|---|-----|------|
| 4 | Don't skip `01-config` in `--app-only` builds | `pi-gen/build.sh` |

### Batch 1C: Kiosk Sandbox Fixes
**Risk:** Kiosk silently fails to write Wayland display path
**Effort:** 30m | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 5 | Add `/run/user/1000` to `ReadWritePaths` | `systemd/framecast-kiosk.service` |
| 6 | `framecast-hostname.service`: change `ProtectSystem=full` → `ProtectSystem=no` (needs `/etc` writes) or use `ReadWritePaths=/etc/hosts /etc/hostname` | `systemd/framecast-hostname.service` |

---

## Phase 2: OTA Pipeline (Critical — Updates must not brick the Pi)

### Batch 2A: Fix Post-Update Script
**Risk:** OTA delivers stale frontend + broken pip install (pip purged during image build)
**Effort:** 3h | **Files:** 3

| # | Fix | File |
|---|-----|------|
| 7 | Keep `python3-pip` installed (remove from purge list) OR bundle pre-built wheels in the repo | `pi-gen/stage2-framecast/02-app/01-run-chroot.sh` |
| 8 | Pre-build frontend assets and commit `app/static/` to tagged releases so OTA `git checkout` delivers them without needing npm | `scripts/post-update.sh` |
| 9 | Remove dead `npm ci && npm run build` branch (node_modules never exist on Pi) | `scripts/post-update.sh` |

### Batch 2B: Health Check Hardening
**Risk:** Health check falls back to untested `main` branch tip
**Effort:** 1h | **Files:** 1

| # | Fix | File |
|---|-----|------|
| 10 | Remove `git checkout --force main` fallback — if tagged rollback fails, halt and log rather than checking out an unknown state | `scripts/health-check.sh` |
| 11 | Verify `pip3` exists before calling `pip3 install` (guard with `command -v pip3`) | `scripts/health-check.sh` |

---

## Phase 3: WiFi Onboarding (High — First-boot experience must work)

### Batch 3A: AP-to-Station Transition
**Risk:** Phone loses connection mid-onboarding, wizard stalls
**Effort:** 2h | **Files:** 3

| # | Fix | File |
|---|-----|------|
| 12 | Return HTTP 202 with `{"status": "connecting", "ssid": "..."}` *before* calling `stop_ap()` — let the client poll for result | `app/api.py` (wifi connect endpoint) |
| 13 | Add polling endpoint `/api/wifi/status` that returns current connection state | `app/api.py` |
| 14 | Update `Onboard.jsx` TEST step to poll `/api/wifi/status` instead of waiting for the original HTTP response | `app/frontend/src/pages/Onboard.jsx` |

### Batch 3B: Setup.jsx + Internet Test
**Risk:** QR code shows wrong IP; internet test fails behind corporate firewalls
**Effort:** 1h | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 15 | Read AP gateway IP from `nmcli` instead of hardcoding `192.168.4.1` | `app/frontend/src/display/Setup.jsx` (via `/api/status` returning AP IP) |
| 16 | Add fallback ping targets (`1.1.1.1`, gateway IP) when `8.8.8.8` is unreachable | `app/api.py` (wifi test endpoint) |

---

## Phase 4: Security Hardening (Medium — Required before distributing to others)

### Batch 4A: Response Headers + Error Leaks
**Effort:** 1h | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 17 | Replace `unsafe-inline` with nonce-based CSP (generate nonce in `spa.html` template) | `app/web_upload.py` |
| 18 | Add `Strict-Transport-Security` header when `HTTPS_ENABLED=yes` | `app/web_upload.py` |
| 19 | Catch `generate_guest_token()` ValueError and return generic 500 instead of leaking config status | `app/api.py` |

### Batch 4B: Service Hardening
**Effort:** 30m | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 20 | Add `User=pi` to `framecast-schedule.service` (hdmi-control runs CEC commands, doesn't need root) | `systemd/framecast-schedule.service` |
| 21 | Remove redundant `sudo` from `updater.py` `systemctl stop` call (already runs as root via update service) | `app/modules/updater.py` |

---

## Phase 5: Reliability Polish (Medium — Prevents edge-case failures)

### Batch 5A: Data Safety
**Effort:** 1h | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 22 | Make `restore_db()` safety backup atomic (tmp + fsync + rename, same pattern as `_atomic_write`) | `app/modules/db.py` |
| 23 | Guard `wifi-manager.service` — if `framecast.service` fails, start AP independently | `scripts/wifi-check.sh` |

### Batch 5B: Pi 3 Memory Safety
**Effort:** 30m | **Files:** 1

| # | Fix | File |
|---|-----|------|
| 24 | Reduce `MemoryMax` on kiosk to 384M (WebKit child inherits cgroup) to leave headroom for framecast service on 1GB Pi 3 | `systemd/framecast-kiosk.service` |

---

## Phase 6: Cleanup + Build Reproducibility (Low — Housekeeping)

### Batch 6A: Dead Code + Stale Config
**Effort:** 30m | **Files:** 3

| # | Fix | File |
|---|-----|------|
| 25 | Delete `install.sh` (deprecated v1 VLC/X11 installer) | `install.sh` |
| 26 | Remove `WEB_PASSWORD` from `.env.example` (replaced by `ACCESS_PIN`) | `app/.env.example` |
| 27 | Upgrade `generate-cert.sh` to P-256 ECDSA with 398-day validity | `scripts/generate-cert.sh` |

### Batch 6B: Build Reproducibility
**Effort:** 30m | **Files:** 2

| # | Fix | File |
|---|-----|------|
| 28 | Pin `requirements.txt` to exact versions (`==` instead of `>=`) | `requirements.txt` |
| 29 | Verify pi-gen commit is pinned (confirmed: `67262a4` — already done, I37) | `pi-gen/build.sh` |

---

## Phase 7: Test Coverage Gaps (Low — Safety net for future changes)

### Batch 7A: Missing Test Modules
**Effort:** 3h | **Files:** 3 new

| # | Fix | File |
|---|-----|------|
| 30 | Add `test_sse.py` — subscribe, notify, coalescing, reconnection replay, max clients | `tests/test_sse.py` |
| 31 | Add `test_services.py` — restart, reboot, shutdown (mocked subprocess) | `tests/test_services.py` |
| 32 | Add `test_boot_config.py` — SSH toggle, boot config reads | `tests/test_boot_config.py` |

---

## Not In Scope (Known Limitations)

| Item | Reason |
|------|--------|
| Captive portal DNS redirect | Requires custom dnsmasq config in NM; low priority — HTTP probes work on most devices |
| Wayland cursor flash on boot | Cosmetic, <1s visibility, hardware-dependent |
| In-memory rate limiter reset on restart | Acceptable for PIN auth on a home device — SQLite persistence would add complexity |
| `onboarding_complete` not read by DisplayRouter | TV display derives state from photo count + WiFi status, which is equivalent |

---

## Execution Order

```
Phase 1A → 1B → 1C (boot stability — do first, each is a separate PR)
Phase 2A → 2B (OTA — depends on Phase 1 being stable)
Phase 3A → 3B (onboarding — can parallel with Phase 2)
Phase 4A → 4B (security — independent)
Phase 5A → 5B (reliability — independent)
Phase 6A → 6B (cleanup — do last)
Phase 7A (tests — do anytime)
```

**Total:** 32 tasks across 13 batches, ~15h estimated work
**Critical path:** Phase 1 + Phase 2 (boot + OTA) — ~6h

---

## Verification

After all phases, rebuild the pi-gen image (full build, not `--app-only`) and run:

1. **Flash to SD card** → boot Pi → verify partition expands
2. **First-boot onboarding** → WiFi AP appears → phone connects → scans QR → completes wizard
3. **Upload lifecycle** → upload photo → appears in slideshow → favorite → delete
4. **OTA update** → tag a test release → Pi picks it up → applies → health check passes
5. **Rollback** → tag a broken release → Pi applies → health check fails → auto-rollback succeeds
6. **Power cycle** → pull power during slideshow → Pi recovers cleanly on reboot
