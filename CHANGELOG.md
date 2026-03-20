# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
