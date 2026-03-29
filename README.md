# FrameCast

[![CI](https://github.com/parthalon025/framecast/actions/workflows/test.yml/badge.svg)](https://github.com/parthalon025/framecast/actions/workflows/test.yml)
[![Build Image](https://github.com/parthalon025/framecast/actions/workflows/build-image.yml/badge.svg)](https://github.com/parthalon025/framecast/actions/workflows/build-image.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turn any TV into a family photo frame -- flash an SD card, plug in the Pi, done.**

Anyone on your WiFi uploads photos from their phone's browser. No app. No cloud. No subscription. Photos appear on the TV within seconds.

---

## Quick Start

1. **Download** the latest `.zip` from [Releases](../../releases)
2. **Flash** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (select "Use custom")
3. **Boot** the Pi -- it displays a setup screen with a QR code
4. **Scan the QR code** from your phone to open the web UI
5. **Upload photos** -- the slideshow starts automatically

No SSH. No terminal. No Linux knowledge required.

---

## Who This Is For

**This is for you if:**
- You want a zero-config photo frame that anyone in the family can add photos to from their phone
- You want a self-hosted solution with no cloud dependency, no subscriptions, and no data leaving your network
- You want something that boots, connects to WiFi, and just works -- even after power outages

**This is not for you if:**
- You need cloud sync (Google Photos, iCloud) -- FrameCast is local-only by design
- You need video playback with audio -- FrameCast displays photos and silent video loops
- You want to run this on non-Pi hardware -- the OS image is Pi-specific (3/4/5, arm64)

---

## Features

| Category | What it does |
|---|---|
| **Slideshow** | Weighted rotation with CSS transitions (fade, slide, Ken Burns, dissolve). "On This Day" memories from EXIF dates. Recency, favorites, and diversity weighting. |
| **Upload** | Drag-and-drop from any browser. Auto-resize, duplicate detection, EXIF GPS extraction. |
| **Albums & Favorites** | Organize photos into albums. Star favorites for 3x slideshow weight. |
| **Multi-user** | Each person gets credit for their uploads. Per-user stats and attribution. |
| **Stats dashboard** | Most shown, least shown, upload timeline, per-user breakdown, storage usage. |
| **Photo map** | GPS EXIF data plotted on an offline SVG world map. |
| **WiFi setup** | Captive portal with onboarding wizard. AP mode auto-starts on first boot. Hotspot fallback when home network is unavailable. |
| **TV control** | HDMI-CEC scheduled on/off. Manual toggle from the web UI. |
| **OTA updates** | GitHub Releases API with SHA-256 verification. Health-check rollback within 90 seconds. |
| **Security** | PIN authentication (4/6 digit), rate limiting, ufw firewall (RFC1918 only), cookie hardening. |
| **Self-healing** | Crash recovery via systemd watchdog. Config restore. Hardware watchdog. |
| **Terminal aesthetic** | superhot-ui green phosphor monitor interface. piOS voice. |

---

## Supported Hardware

| Pi Model | Status |
|----------|--------|
| Raspberry Pi 3B / 3B+ | Supported (64-bit, performance-optimized) |
| Raspberry Pi 4 | Supported |
| Raspberry Pi 5 | Supported |

Any HDMI TV or monitor. A 7" or 10" HDMI display works well as a dedicated frame.

**Requirements:** microSD card (16 GB min, 32 GB recommended), power supply for your Pi model, HDMI cable (micro-HDMI adapter for Pi 4/5).

---

## Architecture

One Flask app serves two surfaces:

```
+-----------------------------------------------+
|                 Raspberry Pi                   |
|                                                |
|  +------------------+   +------------------+  |
|  | framecast-kiosk  |   |  Flask + SSE     |  |     +-----------+
|  | cage + GTK-WebKit|   |  (gunicorn)      |<------>| Phone /   |
|  | /display route   |   |  Upload, API,    |  |WiFi | Computer  |
|  | Preact slideshow |   |  settings, map   |  |     +-----------+
|  +-------+----------+   +--------+---------+  |
|          |                       |             |
|          +----------+------------+             |
|                     |                          |
|             +-------v--------+                 |
|             |  SQLite DB +   |                 |
|             |  ~/media/      |                 |
|             +----------------+                 |
|                                                |
|  systemd services | watchdog | ufw firewall    |
+------------------------------------------------+
                      | HDMI-CEC
                      v
              +---------------+
              |  TV / Monitor |
              +---------------+
```

- **Phone** -- upload, settings, albums, favorites, stats, map, users, update (Preact SPA, 4 nav tabs)
- **TV** -- slideshow with CSS animations, boot sequence, QR codes (Wayland kiosk via cage + GTK-WebKit)
- **Database** -- SQLite with WAL mode, co-located with photos for unified backup

Wayland only -- no X11. The kiosk browser renders the slideshow page served by the same Flask app.

---

## Configuration

All settings live in `/opt/framecast/app/.env` and can be changed from the web UI Settings page.

### Slideshow

| Setting | Default | Description |
|---------|---------|-------------|
| `PHOTO_DURATION` | `10` | Seconds each photo is displayed |
| `TRANSITION_TYPE` | `fade` | `fade`, `slide`, `zoom`, `dissolve`, `none` |
| `TRANSITION_MODE` | `single` | `single` (one type) or `random` (mix) |
| `TRANSITION_DURATION_MS` | `1000` | Transition speed in ms (500-3000) |
| `KENBURNS_INTENSITY` | `moderate` | `subtle`, `moderate`, `dramatic` |
| `PHOTO_ORDER` | `shuffle` | `shuffle`, `newest`, `oldest`, `alphabetical` |
| `QR_DISPLAY_SECONDS` | `30` | QR code duration on boot (0 to disable) |

### Security

| Setting | Default | Description |
|---------|---------|-------------|
| `ACCESS_PIN` | (generated) | PIN shown on TV for authentication |
| `PIN_LENGTH` | `4` | `4` or `6` digits |
| `PIN_ROTATE_ON_BOOT` | `no` | New PIN every boot |

### Display Schedule

| Setting | Default | Description |
|---------|---------|-------------|
| `HDMI_SCHEDULE_ENABLED` | `no` | Automatic TV on/off |
| `HDMI_ON_TIME` | `08:00` | Turn on (24h) |
| `HDMI_OFF_TIME` | `22:00` | Turn off (24h) |
| `DISPLAY_SCHEDULE_DAYS` | `mon,tue,wed,thu,fri,sat,sun` | Active days |

### Server & Media

| Setting | Default | Description |
|---------|---------|-------------|
| `WEB_PORT` | `8080` | HTTP port |
| `MAX_UPLOAD_MB` | `200` | Max upload size |
| `AUTO_RESIZE_MAX` | `1920` | Max dimension for auto-resize (0 to disable) |
| `MEDIA_DIR` | `/home/pi/media` | Photo storage path |
| `AUTO_UPDATE_ENABLED` | `no` | Check for OTA updates daily |

---

## Building from Source

### Prerequisites

- Node.js 18+ (frontend build)
- Python 3.11+ with pip
- Linux x86_64 with sudo (native image build) or Docker

### Frontend

```bash
cd app/frontend
npm install
npm run build
```

### Run Locally

```bash
pip install flask gunicorn pillow
cd app
gunicorn -c gunicorn.conf.py web_upload:app
```

Open `http://localhost:8080` for the phone UI. The TV display (`/display`) requires a Wayland compositor.

### Build the OS Image

Built with [pi-gen](https://github.com/RPi-Distro/pi-gen) (bookworm-arm64):

```bash
cd pi-gen
./build.sh                 # Full build (~35 min first time)
./build.sh --app-only      # Rebuild app stage only (~5 min)
./build.sh --base-only     # OS layer without app
./build.sh --continue      # Add app layer to existing base
./build.sh --docker        # Build via Docker
./build.sh --clean         # Wipe work/ and deploy/ first
```

Output: `pi-gen/pi-gen/deploy/image_*-FrameCast-v*.zip`

---

## Project Structure

```
framecast/
|-- app/
|   |-- web_upload.py            # Flask app factory + static serving
|   |-- api.py                   # REST API (~70 routes)
|   |-- sse.py                   # Server-Sent Events
|   |-- gunicorn.conf.py         # workers=1 (mandatory — SSE singleton)
|   |-- modules/                 # db, rotation, users, cec, auth, wifi, updater, config, media, services, rate_limiter, boot_config
|   |-- frontend/src/            # Preact + esbuild + superhot-ui
|   |-- static/                  # Built CSS/JS
|   |-- templates/               # spa.html (SPA shell)
|-- pi-gen/                      # OS image build
|-- scripts/                     # health-check, HDMI control, post-update, smoke test
|-- systemd/                     # 6 service/timer units
|-- tests/                       # 368 tests (340 Python + 15 vitest + 13 bats)
```

---

## CI/CD

### PR Gate (16 jobs)

| Job | What |
|-----|------|
| lint-python | ruff |
| shellcheck | all `.sh` files |
| typecheck | mypy strict |
| pytest | unit, property, concurrency, fault injection, benchmarks |
| integration | gunicorn + real endpoint verification |
| build-frontend | esbuild + asset verification |
| test-frontend | vitest (SSE client) |
| test-shell | bats (health-check rollback) |
| architecture | structural invariants |
| smoke | file structure, permissions, systemd units |
| Claude Code Review | AI review against CLAUDE.md conventions |
| Claude Security Review | OWASP analysis (path-triggered) |
| actionlint | workflow validation |
| commitlint | conventional commits |
| CodeQL | SAST |
| gitleaks | secret scanning |

### Release Pipeline (on `v*` tag)

1. Full test suite gate
2. Pi-gen image build (~41 min, cached ~5 min)
3. Structural image validation (boot partition + rootfs + systemd units)
4. SBOM generation (CycloneDX -- Python + Node)
5. Cosign keyless signing (Sigstore OIDC)
6. SLSA Build Level 2 attestation
7. GitHub Release (image + checksums + signatures + SBOMs)
8. Telegram notification

**Automation:** [release-please](https://github.com/googleapis/release-please) (auto VERSION + CHANGELOG), [Dependabot](https://docs.github.com/en/code-security/dependabot) (weekly pip/npm, monthly Actions), branch protection (squash-only, linear history).

### Verify a Release

```bash
# Cosign signature
cosign verify-blob \
  --certificate image.pem --signature image.sig \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  image.zip

# SLSA provenance
gh attestation verify image.zip -R parthalon025/framecast
```

---

## Troubleshooting

### WiFi won't connect

- **Check the password.** Most common cause is a typo. Re-enter via the web UI.
- **Network not found.** Move the Pi closer to the router.
- **AP mode stuck.** Power cycle the Pi. It will restart the captive portal.
- **Hidden network.** FrameCast cannot scan hidden SSIDs.

### TV is black

- **Check HDMI.** Unplug and re-plug.
- **Power supply.** Undervoltage throttling may prevent display output. Use the official PSU.
- **Schedule.** If enabled, the display turns off at the configured time.
- **Kiosk crash.** `journalctl -u framecast-kiosk -n 50`. Auto-restarts within 60s.

### Photos not showing

- **Upload completed?** Check the upload page for errors.
- **File format.** Only standard image/video formats accepted.
- **Disk full.** Check Settings for storage usage.
- **Quarantined.** Corrupt images are auto-quarantined. Check `journalctl -u framecast`.

### OTA update failed

- **No internet.** Updates require internet access.
- **SHA mismatch.** Try again. If persistent, report an issue.
- **Rollback.** Health-check timer auto-rolls back within 90 seconds.

### Debugging

```bash
journalctl -u framecast -n 100        # Web server
journalctl -u framecast-kiosk -n 50   # Display
journalctl -u wifi-manager -n 50      # WiFi
systemctl status framecast framecast-kiosk wifi-manager
sudo ufw status                       # Firewall
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and PR guidelines.

## API

See [API.md](API.md) for complete endpoint documentation.

## Credits

Based on [pi-video-photo-slideshow](https://github.com/bobburgers7/pi-video-photo-slideshow) by bobburgers7.

## License

MIT -- see [LICENSE](LICENSE).
