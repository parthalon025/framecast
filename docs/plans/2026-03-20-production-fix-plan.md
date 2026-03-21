# FrameCast Production Fix Plan

**Date:** 2026-03-20
**Source:** 12-agent production review findings
**Branch:** fix/production-hardening (continuing)

## Execution Batches

### Batch 1: Quick Fixes (parallel, independent)

| Task | Finding | Files | Size |
|------|---------|-------|------|
| A: Auth bypass fix | C11 | `auth.py` | S |
| B: Non-atomic restore_db | C14 | `db.py` | S |
| C: Disk full trap | C15 | `web_upload.py`, `db.py` | S |
| D: Reboot cascade prevention | Theme 5, I12 | `systemd/*.service`, pi-gen swap | S |
| E: CI hardening | Prevention | `.github/workflows/test.yml` | M |

### Batch 2: Medium Fixes (parallel after Batch 1 commit)

| Task | Finding | Files | Size |
|------|---------|-------|------|
| F: Display state machine | C5, Theme 3 | `DisplayRouter.jsx`, `api.py`, `sse.py` | M |
| G: OTA pipeline | C6-C8, Theme 2 | `updater.py`, `health-check.sh`, build scripts | M |

### Batch 3: WiFi Unification (sequential, architectural)

| Task | Finding | Files | Size |
|------|---------|-------|------|
| H: WiFi unification | C1-C5, Theme 1 | `wifi.py`, delete `wifi-manager.sh`, `Onboard.jsx`, `DisplayRouter.jsx`, systemd | L |

## Acceptance Criteria

- [ ] Auth bypass: `_is_ap_active()` checks actual AP state via nmcli
- [ ] restore_db: uses atomic tmp+fsync+rename
- [ ] Disk full: delete-all tries file unlink before DB quarantine write
- [ ] No `StartLimitAction=reboot` on any service
- [ ] Pi 3 swap configured in pi-gen
- [ ] ShellCheck passes on all .sh files
- [ ] Integration test runs Flask + hits /api/status + uploads photo
- [ ] systemd validation catches WatchdogSec without Type=notify
- [ ] DisplayRouter polls /api/status periodically, handles wifi:connected
- [ ] OTA: post-update pip install, proper SHA verification, frontend rebuild
- [ ] WiFi: single AP system, AP auto-starts on first boot, phone reconnection after transition
