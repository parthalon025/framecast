# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.1](https://github.com/parthalon025/framecast/compare/v2.2.0...v2.2.1) (2026-03-29)


### Bug Fixes

* resolve CI failures and include 01-config in --app-only builds ([5031cfc](https://github.com/parthalon025/framecast/commit/5031cfc51a9d9e6e32071305191bf0a345f628a1)), closes [#131](https://github.com/parthalon025/framecast/issues/131)
* SD card audit — 7 fixes for boot failures and image issues ([#129](https://github.com/parthalon025/framecast/issues/129)) ([268e56f](https://github.com/parthalon025/framecast/commit/268e56f153e0a0fab692e199b6a02fb791c90203))

## [2.2.0](https://github.com/parthalon025/framecast/compare/v2.1.0...v2.2.0) (2026-03-21)


### Features

* API consolidation + superhot-ui maximization ([#91](https://github.com/parthalon025/framecast/issues/91)) ([5a72a96](https://github.com/parthalon025/framecast/commit/5a72a96871b720df149577115acb4f5935148802))
* Phase 3 — 9 phone UX polish improvements ([#82](https://github.com/parthalon025/framecast/issues/82)) ([ba613d8](https://github.com/parthalon025/framecast/commit/ba613d8aacf63b4468841dc32d7c98bce858a488))
* Phase 4 — TV display improvements ([#52](https://github.com/parthalon025/framecast/issues/52), [#66](https://github.com/parthalon025/framecast/issues/66), [#60](https://github.com/parthalon025/framecast/issues/60), [#62](https://github.com/parthalon025/framecast/issues/62), [#48](https://github.com/parthalon025/framecast/issues/48)) ([#83](https://github.com/parthalon025/framecast/issues/83)) ([dea60d0](https://github.com/parthalon025/framecast/commit/dea60d095c2caee28fe8975ad6ea7886c9fbdf04))
* Phase 5 — media pipeline improvements ([#47](https://github.com/parthalon025/framecast/issues/47), [#42](https://github.com/parthalon025/framecast/issues/42), [#29](https://github.com/parthalon025/framecast/issues/29), [#46](https://github.com/parthalon025/framecast/issues/46)) ([2af5609](https://github.com/parthalon025/framecast/commit/2af560960c095a018f75b1dbb44f4438af751710))
* Phase 6 — real-time features ([#39](https://github.com/parthalon025/framecast/issues/39), [#74](https://github.com/parthalon025/framecast/issues/74), [#63](https://github.com/parthalon025/framecast/issues/63), [#73](https://github.com/parthalon025/framecast/issues/73), [#51](https://github.com/parthalon025/framecast/issues/51)) ([#87](https://github.com/parthalon025/framecast/issues/87)) ([a9ae38c](https://github.com/parthalon025/framecast/commit/a9ae38ca130bc308fd441804779e35b4de7fd3cb))
* Phase 7 — network & setup improvements ([#88](https://github.com/parthalon025/framecast/issues/88)) ([d10691c](https://github.com/parthalon025/framecast/commit/d10691ca57f42099a29ffb6b37a2683f6a336e0f))
* Phase 8 — advanced features ([#44](https://github.com/parthalon025/framecast/issues/44), [#45](https://github.com/parthalon025/framecast/issues/45), [#57](https://github.com/parthalon025/framecast/issues/57), [#58](https://github.com/parthalon025/framecast/issues/58), [#68](https://github.com/parthalon025/framecast/issues/68), [#61](https://github.com/parthalon025/framecast/issues/61)) ([#89](https://github.com/parthalon025/framecast/issues/89)) ([102a606](https://github.com/parthalon025/framecast/commit/102a6065e5dfe9f24c9da4c27770414ff3b419a5))
* superhot-ui atmosphere system for TV display surface ([#93](https://github.com/parthalon025/framecast/issues/93)) ([3988dae](https://github.com/parthalon025/framecast/commit/3988dae543f940b7d258982bc656fac63d85fe80))


### Bug Fixes

* build-image workflow YAML parse error and missing workflow_call ([#114](https://github.com/parthalon025/framecast/issues/114)) ([2b3e28a](https://github.com/parthalon025/framecast/commit/2b3e28a886828f55dd935256757a95d9429e0ae7))
* comprehensive audit fixes — 41 tasks across 11 batches ([#79](https://github.com/parthalon025/framecast/issues/79)) ([80730f6](https://github.com/parthalon025/framecast/commit/80730f64feb1ad47cd041a390ad64ebef0c9db90))
* downgrade media directory check to warning in image validation ([#121](https://github.com/parthalon025/framecast/issues/121)) ([dc75f23](https://github.com/parthalon025/framecast/commit/dc75f2376cb09f692c5bc88af89d44d162c72606))
* move firewall setup from 02-app to 03-system stage ([#118](https://github.com/parthalon025/framecast/issues/118)) ([e898512](https://github.com/parthalon025/framecast/commit/e8985128d2ffa1c346b4b450ccd5336149ef5388))
* OTA update pipeline — init git repo in pi-gen, create update-check.sh, pass SHA to apply ([8c61d1e](https://github.com/parthalon025/framecast/commit/8c61d1e20a8d2445045e28e3fa30eafe0a417fa9))
* Phase 1 hardening — 9 security and reliability fixes ([e84a399](https://github.com/parthalon025/framecast/commit/e84a3996371cf183048fbf6d508dd26a0ecf3474))
* Phase 1 hardening — 9 security and reliability fixes ([2c6b4fd](https://github.com/parthalon025/framecast/commit/2c6b4fd7a0d733c366de94aa7755a1f594e0eb49))
* Phase 2 — API integration tests + cache-bust on OTA update ([#81](https://github.com/parthalon025/framecast/issues/81)) ([0516cea](https://github.com/parthalon025/framecast/commit/0516cea1b78a0e2e0e29ac7dbbd2e5d239104146))
* polish PhoneLayout search — header bar, SVG icon, lightbox integration ([3100e90](https://github.com/parthalon025/framecast/commit/3100e90f3e76748fd12bcbd0c23278a55eabbd0e))
* production hardening — OTA safety, pi-gen build, kiosk reliability, firewall ([#95](https://github.com/parthalon025/framecast/issues/95)) ([bd0355f](https://github.com/parthalon025/framecast/commit/bd0355f8f6ff0320a751f9517657ec717938a4e4))
* Production Hardening v2.1 — 90 findings from 12-agent review ([#110](https://github.com/parthalon025/framecast/issues/110)) ([b1fade0](https://github.com/parthalon025/framecast/commit/b1fade031e9f1032ad9949bb42b46336ff9a521c))
* reliability hardening — 19 fixes across systemd, shell, Python, security ([#85](https://github.com/parthalon025/framecast/issues/85)) ([97fb85c](https://github.com/parthalon025/framecast/commit/97fb85c74b8eeeb9ccdca70c185431cc67a1b72f))
* replace QEMU boot test with structural image validation ([#120](https://github.com/parthalon025/framecast/issues/120)) ([0b9cf2e](https://github.com/parthalon025/framecast/commit/0b9cf2e997abfe6004eaf14db671a2aab1b528d0))
* resolve ruff lint errors — remove unused imports, noqa late import ([24b2d62](https://github.com/parthalon025/framecast/commit/24b2d6238326d6fb9a8f6ac51a5cdac42e55ec94))
* seed RNG in diversity test to prevent CI flakes ([#123](https://github.com/parthalon025/framecast/issues/123)) ([76ad3c5](https://github.com/parthalon025/framecast/commit/76ad3c5353ebeaaf9f2e9ed41759d51079f00181))
* sync VERSION and release-please manifest to v2.1.0 ([#115](https://github.com/parthalon025/framecast/issues/115)) ([3675802](https://github.com/parthalon025/framecast/commit/367580222b71ef9039b40208ed97f4e3f9e212eb))


### Performance Improvements

* cache pi-gen base rootfs between CI builds ([#119](https://github.com/parthalon025/framecast/issues/119)) ([e1e3814](https://github.com/parthalon025/framecast/commit/e1e3814ac97d2e0a58c46017cf40a0623bea1467))

## [2.0.1] - 2026-03-20

### Fixed
- Slideshow now includes all photos, not just 500 most recent
- Slideshow retries indefinitely with visible CONNECTION LOST indicator on SSE failure
- DisplayRouter uses `createSSE` helper with exponential backoff (was raw `EventSource`)
- `photo:favorited` SSE event now actually emitted on favorite toggle
- `delete-all` returns JSON for XHR/fetch clients; still redirects for form submissions
- Orphan thumbnail cleanup now scans subdirectories and logs individual failures
- All bare `except` blocks now log before returning fallback (Lesson #1418)
- All file `unlink()` calls protected with `OSError` handling
- Fetch errors surface via toasts; `fetchWithTimeout` used consistently
- Update page SSE error handler fixed (stale closure)
- Quarantined files blocked from `/media/` route (404)
- `schedule_days` validated as comma-separated integers 0–6
- Stats buffer capped at 500 entries to prevent OOM on persistent DB errors
- Leaflet CSS bundled locally — works on offline Pi
- piOS STANDBY voice normalized across all in-progress labels
- Facility state set to `normal` at app init

### Added
- Public DB API (`get_playlist_candidates`, `unquarantine_photo`, `compute_sha256`, `prune_quarantined`, `bulk_quarantine_all`, `create_user_returning_row`, `delete_user_reassign`) — routes no longer reach into `_write_lock` directly
- `DELETE /api/users/<id>` endpoint — reassigns photos to default user before deleting
- Quarantined photos older than 30 days pruned on startup
- Index on `checksum_sha256` for faster duplicate detection
- Test suites for `auth.py`, `rate_limiter.py`, and `config.py` (160 tests total, was 129)
- PWA meta tags on SPA template
- `:focus-visible` rules for all custom interactive elements
- `forced-colors` overrides for high contrast mode

### Changed
- GPS extraction in `index()` replaced with lightweight DB query (was heavy EXIF scan)
- All systemd units ensured present in pi-gen image
- Service hardening: `ReadWritePaths` fixed, `WatchdogSec` removed from kiosk, sandbox restored

### Performance
- Mobile: SSE paused when page is backgrounded (battery drain reduction)
- Mobile: touch targets enlarged to 44px minimum
- Mobile: all inputs set to 16px minimum font-size (prevents iOS auto-zoom)
- Mobile: `PhoneLayout` uses `dvh` units; Map nav overlap fixed; offline banner respects safe area
- Mobile: Lightbox safe area, delete confirmation, and video muted attribute fixed

---

## [2.0.0] - 2026-03-19

### Added
- Flash-and-go OS image (pi-gen based, arm64)
- Browser-based slideshow with CSS transitions (fade, slide, Ken Burns)
- superhot-ui frontend with green phosphor terminal aesthetic
- WiFi captive portal with onboarding wizard
- Server-Sent Events for real-time display updates
- OTA update system with health-check rollback
- PIN authentication for web UI
- Photo map with GPS EXIF data
- Wayland kiosk display (cage + GTK-WebKit, no X11)
- HDMI schedule via wlr-randr
- GitHub Actions CI/CD pipeline

### Changed
- Replaced VLC slideshow with browser-based engine
- Replaced X11/openbox with Wayland/cage
- Flask behind gunicorn with multi-core support
- Rewrote frontend as Preact SPA

### Removed
- VLC dependency
- X11/openbox dependency
- Server-rendered Jinja2 templates (replaced by SPA)

## [1.0.0] - 2026-03-18

### Added

- **Slideshow engine** using VLC with full-screen display on any HDMI monitor or TV.
  - Configurable photo duration, shuffle, and loop modes.
  - Automatic media change detection with debounced restart.
  - Crash recovery with exponential backoff (up to 5 consecutive failures).
  - Systemd watchdog integration for liveness monitoring.
  - X11 display readiness wait on boot.

- **Web upload server** (Flask) for managing photos and videos from any browser.
  - Drag-and-drop and file browser upload with progress indication.
  - Gallery view with lightbox preview for photos.
  - Video thumbnail generation via ffmpeg.
  - Auto-resize of oversized images using Pillow (configurable max dimension).
  - Individual file deletion and bulk delete-all with confirmation.
  - Disk space indicator on the upload page.
  - Duplicate filename handling with unique suffix.

- **Settings page** for runtime configuration without SSH.
  - Photo duration, shuffle, loop, HDMI schedule, upload limits.
  - File extension whitelist with forbidden extension validation.
  - Apply-immediately option to restart the slideshow on save.
  - Device power controls (reboot, shutdown) from the browser.

- **REST API endpoints** for programmatic access.
  - `GET /api/status` - photo/video counts, disk usage, slideshow state.
  - `POST /api/restart-slideshow` - restart the slideshow service.
  - `POST /api/reboot` - reboot the Pi.
  - `POST /api/shutdown` - shut down the Pi.

- **WiFi AP fallback** for headless and offline operation.
  - Automatic hotspot creation (SSID: PiPhotoFrame) when no WiFi is available.
  - Dual backend support: NetworkManager (nmcli) for Bookworm+, hostapd/dnsmasq for Bullseye.
  - Periodic reconnection attempts to known WiFi networks.
  - Seamless switching between client and AP modes.

- **Welcome screen** with QR code shown when no photos are uploaded.
  - Auto-generated PNG with setup instructions and web UI URL.
  - QR code generated via qrencode for easy phone scanning.
  - Dynamic IP address detection.

- **HDMI schedule** to turn the display off at night and on in the morning.
  - Configurable on/off times via the web settings page.
  - Cron-based scheduling managed by the installer.
  - Manual on/off/status control via hdmi-control.sh.
  - Multi-method display control (vcgencmd, tvservice, xrandr).

- **One-step installer** (install.sh) handling all setup.
  - Automatic user detection (supports Pi OS Bookworm without default pi user).
  - System package installation (VLC, ffmpeg, xdotool, watchdog, qrencode, avahi).
  - Systemd service creation for slideshow, web server, and WiFi manager.
  - Scoped sudoers entries for slideshow restart, reboot, and shutdown.
  - Desktop auto-login configuration via raspi-config.
  - Hardware watchdog setup for automatic reboot on system freeze.
  - Screen blanking disabled in lightdm and via raspi-config.
  - GPU memory allocation for Pi 3 and older models.
  - mDNS/avahi setup for photoframe.local discovery.
  - Configuration preservation across re-installs.

- **SD card longevity** optimizations.
  - Journal size limits (50 MB max, 7-day retention).
  - /tmp mounted as tmpfs (RAM disk).
  - noatime added to root filesystem.

- **Security hardening** throughout.
  - Flask secret key auto-generated and persisted.
  - .env file permissions set to 600.
  - Systemd service sandboxing (ProtectSystem, NoNewPrivileges, PrivateTmp, MemoryMax).
  - Path traversal prevention on file delete.
  - MEDIA_DIR validation against safe parent directories.
  - Forbidden file extension list to block executable uploads.
  - Security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
  - Atomic .env writes with fsync to prevent corruption on power loss.

- **Modular Python codebase** with separated concerns.
  - `modules/config.py` - .env read/write with caching and atomic saves.
  - `modules/media.py` - file listing, disk usage, extension validation.
  - `modules/services.py` - systemd service status and restart controls.

- **Makefile** with targets for install, uninstall, update, status, logs, and test.
- **Smoke test script** for quick installation validation.
- **Project documentation** including README, CONTRIBUTING guide, and CHANGELOG.

### Supported Hardware

- Raspberry Pi 3B, 3B+, 4, and 5.
- Any HDMI-connected TV or monitor.
- Raspberry Pi OS with Desktop (Bullseye or Bookworm, 32-bit or 64-bit).

### Supported Media Formats

- **Photos:** JPG, JPEG, PNG, BMP, GIF, WEBP, TIFF.
- **Videos:** MP4, MKV, AVI, MOV, WEBM, M4V, MPG, MPEG.
