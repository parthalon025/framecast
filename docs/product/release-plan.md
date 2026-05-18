# Release Plan — FrameCast v2.2.1
**Target date:** 2026-03-29
**Release type:** Patch
**Release method:** release-please (PR #130) → GitHub Release → pi-gen image build
**Status:** RELEASED (2026-03-29)

## Scope

Patch release containing 9 fixes across two PRs:

### PR #129 — SD card audit (7 fixes)
1. **cmdline.txt boot params** — fixed `rootfstype=ext4` and `fsck.repair=yes`
2. **pi-gen config.txt** — corrected `dtoverlay=vc4-kms-v3d` (was `fkms`), proper `arm_64bit=1`
3. **pi-gen build.sh** — fixed stage directory detection and cleanup logic
4. **Image validation** — added structural checks for boot/root partitions
5. **Health check** — improved rollback tag validation and error handling
6. **HDMI script** — fixed `cec-ctl` command syntax for Bookworm
7. **Gunicorn config** — secured bind address and timeout settings

### PR #132 — CI fixes + cmdline.txt (closes #131)
8. **cmdline.txt `init_resize.sh`** — `--app-only` builds no longer skip `01-config` stage
9. **CI pipeline** — updated claude-code-action to v1.0.81, fixed ShellCheck SC2154/SC2035, added OIDC permissions

## Release Checklist

### Pre-Release
- [x] All bug fixes merged to main (PR #129 + PR #132)
- [x] No open P0 bugs (remaining issues are P1/P2: #106, #105)
- [x] CHANGELOG.md auto-updated by release-please
- [x] VERSION auto-bumped to 2.2.1 by release-please
- [x] 363 Python tests passing (`make pytest`)
- [x] Frontend tests passing (`make test-frontend`)
- [x] Shell tests passing (`make test-shell`)
- [x] CI pipeline: 16 jobs green on main (CI Pass required check)
- [x] Security review: no new auth/crypto/network changes in this patch

### Release
- [x] Merge release-please PR #130 (created tag `v2.2.1` automatically)
- [x] GitHub Release created with changelog notes (2026-03-29)
- [ ] Trigger pi-gen image build: `cd pi-gen && ./build.sh`
- [ ] Verify built image boots in QEMU: `make test-image` (or structural validation)
- [ ] Upload `.img.xz` to GitHub Release assets
- [ ] Telegram notification sent (automated via CI)

### Post-Release (first 24 hours)
- [ ] Flash SD card and verify Pi boots to slideshow
- [ ] Verify photo upload from phone works end-to-end
- [ ] Check kiosk service starts and displays slideshow
- [ ] Verify CEC TV control works (`cec-ctl` commands)
- [ ] Confirm health check timer runs without false rollback
- [ ] Rollback plan ready (see below)

## Messaging

### Internal announcement
FrameCast v2.2.1 — patch release fixing 7 boot/image issues found during SD card audit. All fixes are in pi-gen build system and boot scripts; no application logic changes.

### Public announcement
N/A — personal project, no public users yet.

## Rollback Plan
**Trigger:** Pi fails to boot, enters reboot loop, or kiosk service crashes repeatedly.

**Steps:**
1. Reflash SD card with v2.2.0 image (keep backup image on workstation)
2. If already deployed: `git tag -s rollback-v2.2.1 -m "rollback" && git push origin rollback-v2.2.1`
3. Health check timer will detect rollback tag and revert to previous version
4. Verify boot and slideshow operation

**Nuclear option:** Flash stock Raspberry Pi OS Bookworm, then run `pi-gen/build.sh` from v2.2.0 tag.

## Success Criteria (72 hours post-flash)
- [ ] Pi boots to slideshow within 60 seconds of power-on
- [ ] No reboot loops or kernel panics in `journalctl`
- [ ] Photo uploads from phone complete successfully
- [ ] CEC standby/wake schedule operates correctly
- [ ] Health check timer reports healthy (no false rollback triggers)
- [ ] SD card filesystem shows `ext4` with `fsck.repair` enabled

## Dependencies on Next Release (v2.2.2)
- Dependabot: picomatch 4.0.4, vitest 4.1.1, happy-dom 20.8.8, gunicorn 25.2.0
- Issue #106: OTA pipeline (delivers source only, no deps/frontend/migrations)
- Issue #105: WiFi provisioning (dual system conflict, no first-boot flow)
- Production readiness plan: `docs/plans/2026-03-28-production-readiness-plan.md` (32 tasks, 7 phases)
