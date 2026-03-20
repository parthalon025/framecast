# FrameCast

**Turn any TV into a family photo frame -- flash, boot, done.**

FrameCast is a ready-to-flash OS image for Raspberry Pi. Download the image, write it to an SD card, plug the Pi into your TV, and you have a photo frame. No SSH, no terminal, no Linux knowledge required.

Anyone on your WiFi can upload photos from their phone's browser. No app, no cloud, no subscription.

---

## Quick Start

1. **Download** the latest `.img.xz` from [Releases](../../releases)
2. **Flash** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (select "Use custom" and pick the downloaded file)
3. **Boot** the Pi -- it displays a setup screen with a QR code
4. **Scan the QR code** from your phone to open the web UI
5. **Upload** photos -- they appear on the TV within seconds

The slideshow starts automatically. No configuration required.

---

## Features

- **Browser-based slideshow** with weighted rotation, CSS transitions (fade, slide, Ken Burns), and "On This Day" memories
- **Drag-and-drop upload** from any phone, tablet, or computer
- **Favorites and albums** for content curation
- **Multi-user support** -- each person gets credit for their uploads
- **Stats dashboard** -- most shown, least shown, upload timeline, per-user breakdown
- **WiFi captive portal** with onboarding wizard -- no SSH or terminal needed
- **HDMI-CEC TV control** -- scheduled on/off, manual toggle from the web UI
- **OTA updates** with SHA-256 verification and health-check rollback
- **PIN authentication** (4 or 6 digits) with rate limiting and cookie hardening
- **Firewall** (ufw) -- only allows traffic from your local network
- **superhot-ui terminal aesthetic** -- green phosphor monitor interface
- **Photo map** plotting GPS EXIF data on an offline SVG world map
- **Server-Sent Events** for real-time display updates with reconnection support
- **Self-healing** -- crash recovery, hardware watchdog, config restore
- **WiFi hotspot fallback** when your home network is unavailable
- **SQLite content model** with duplicate detection and SD card write optimization

---

## Supported Hardware

| Pi Model | Status |
|----------|--------|
| Raspberry Pi 3B / 3B+ | Supported (64-bit, performance-optimized) |
| Raspberry Pi 4 | Supported (64-bit) |
| Raspberry Pi 5 | Supported (64-bit) |

Any HDMI TV or monitor works. A small 7" or 10" HDMI display works well as a dedicated frame.

**Requirements:**
- microSD card (16 GB minimum, 32 GB recommended)
- Power supply for your Pi model
- HDMI cable (micro-HDMI adapter for Pi 4/5)

---

## Architecture

FrameCast is one Flask app serving two surfaces:

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

- **Phone** surface: upload, settings, albums, favorites, stats, map, users, update (Preact SPA)
- **TV** surface: slideshow with CSS animations, boot sequence, QR codes (Wayland kiosk)
- **Database**: SQLite with WAL mode, co-located with photos for unified backup

Wayland only -- no X11. The kiosk browser (cage compositor + GTK-WebKit) renders the slideshow page served by the same Flask app.

---

## Configuration Reference

All settings are in `/opt/framecast/app/.env` and can be changed from the web UI Settings page.

### Slideshow

| Setting | Default | Description |
|---------|---------|-------------|
| `PHOTO_DURATION` | `10` | Seconds each photo is displayed |
| `SHUFFLE` | `yes` | Randomize photo order |
| `TRANSITION_TYPE` | `fade` | Effect: `fade`, `slide`, `zoom`, `dissolve`, `none` |
| `TRANSITION_MODE` | `single` | `single` (one type) or `random` (mix transitions) |
| `TRANSITION_DURATION_MS` | `1000` | Transition speed in milliseconds (500-3000) |
| `KENBURNS_INTENSITY` | `moderate` | Ken Burns zoom: `subtle`, `moderate`, `dramatic` |
| `PHOTO_ORDER` | `shuffle` | Order: `shuffle`, `newest`, `oldest`, `alphabetical` |
| `QR_DISPLAY_SECONDS` | `30` | How long the QR code shows on boot (0 to disable) |

### Web Server

| Setting | Default | Description |
|---------|---------|-------------|
| `WEB_PORT` | `8080` | HTTP port (not editable from web UI) |
| `MAX_UPLOAD_MB` | `200` | Maximum upload file size in MB |
| `AUTO_RESIZE_MAX` | `1920` | Max dimension for auto-resize (0 to disable) |

### Security

| Setting | Default | Description |
|---------|---------|-------------|
| `ACCESS_PIN` | (generated) | PIN displayed on TV screen for authentication |
| `PIN_LENGTH` | `4` | PIN digit count: `4` or `6` |
| `PIN_ROTATE_ON_BOOT` | `no` | Generate a new PIN every time the Pi boots |
| `FLASK_SECRET_KEY` | (generated) | Secret key for cookie signing |

### Display Schedule

| Setting | Default | Description |
|---------|---------|-------------|
| `HDMI_SCHEDULE_ENABLED` | `no` | Enable automatic TV on/off schedule |
| `HDMI_ON_TIME` | `08:00` | Time to turn TV on (HH:MM, 24-hour) |
| `HDMI_OFF_TIME` | `22:00` | Time to turn TV off (HH:MM, 24-hour) |
| `DISPLAY_SCHEDULE_DAYS` | `mon,tue,wed,thu,fri,sat,sun` | Days schedule is active |

### Updates

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_UPDATE_ENABLED` | `no` | Check for OTA updates daily |
| `GITHUB_OWNER` | `parthalon025` | GitHub repo owner (for forks) |
| `GITHUB_REPO` | `framecast` | GitHub repo name (for forks) |

### Media

| Setting | Default | Description |
|---------|---------|-------------|
| `MEDIA_DIR` | `/home/pi/media` | Photo/video storage path (not editable from web UI) |
| `IMAGE_EXTENSIONS` | `.jpg,.jpeg,.png,.bmp,.gif,.webp,.tiff` | Accepted image types |
| `VIDEO_EXTENSIONS` | `.mp4,.mkv,.avi,.mov,.webm,.m4v,.mpg,.mpeg` | Accepted video types |

---

## Building from Source

### Prerequisites

- Node.js 18+ (frontend build)
- Python 3.11+ with pip (backend)
- Docker (OS image build only)

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

Open `http://localhost:8080` for the phone UI. The kiosk display (`/display`) requires a Wayland compositor -- test visually on a Pi or use a browser.

### Build the OS Image

The flashable `.img.xz` is built with [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker:

```bash
cd pi-gen
bash build.sh
```

Output lands in `pi-gen/deploy/`. Takes 20-60 minutes depending on your machine.

### Project Structure

```
framecast/
|-- app/
|   |-- web_upload.py            # Flask web server (entry point)
|   |-- api.py                   # REST API (30+ endpoints) + rate limiting
|   |-- sse.py                   # Server-Sent Events with reconnection
|   |-- gunicorn.conf.py         # Gunicorn (workers=1, gthread)
|   |-- modules/
|   |   |-- db.py                # SQLite content model (photos, albums, tags, users, stats)
|   |   |-- rotation.py          # Weighted slideshow playlist (recency, favorites, diversity)
|   |   |-- users.py             # Multi-user management + stats aggregation
|   |   |-- cec.py               # HDMI-CEC TV control (cec-ctl)
|   |   |-- auth.py              # PIN authentication (4/6 digit) + CSRF
|   |   |-- rate_limiter.py      # Shared rate limiter (API + PIN)
|   |   |-- config.py            # .env configuration (atomic writes)
|   |   |-- media.py             # Image/video processing + GPS extraction
|   |   |-- updater.py           # OTA updates with SHA256 verification
|   |   |-- wifi.py              # WiFi provisioning (nmcli, AP mode)
|   |-- frontend/
|   |   |-- src/
|   |   |   |-- styles/          # CSS architecture (8 files)
|   |   |   |-- lib/             # Shared JS (sse.js, fetch.js, format.js)
|   |   |   |-- components/      # Reusable (PhotoCard, Lightbox, PinGate, etc.)
|   |   |   |-- pages/           # Phone UI (Upload, Albums, Settings, Map, Stats, etc.)
|   |   |   |-- display/         # TV display (Slideshow, Boot, Setup, Welcome)
|   |   |-- esbuild.config.js    # Build configuration
|   |-- static/                  # Built CSS/JS assets
|   |-- templates/               # HTML templates (SPA shell, legacy pages)
|-- pi-gen/                      # OS image build (Docker-based)
|-- scripts/                     # Health check, HDMI control, smoke tests
|-- systemd/                     # 6 service/timer definitions
|-- tests/                       # 160 tests (db, rotation, users, cec, albums, auth, rate_limiter, config)
|-- API.md                       # Full endpoint documentation
|-- CONTRIBUTING.md              # Dev setup + PR guidelines
|-- VERSION                      # Current version (semver)
```

### CI/CD

- **Pull requests** trigger lint (ruff) and frontend build checks
- **Tag pushes** (`v*`) build the OS image via pi-gen Docker
- **Releases** are created automatically with the image and SHA256 checksum

---

## Troubleshooting

### WiFi won't connect

- **Check the password.** The most common cause is a typo. Re-enter via the web UI.
- **Network not found.** Move the Pi closer to the router. The Pi 3 has limited WiFi range.
- **AP mode stuck.** Power cycle the Pi. It will restart the captive portal.
- **Hidden network.** FrameCast cannot scan hidden SSIDs. Either unhide it or configure WiFi via `wpa_supplicant.conf` on the boot partition.

### TV is black

- **Check HDMI connection.** Unplug and re-plug the HDMI cable.
- **Check power supply.** An undervoltage-throttled Pi may not drive the display. Use the official power supply for your model.
- **HDMI schedule.** If the schedule is enabled, the display turns off at the configured time. Check Settings or disable `HDMI_SCHEDULE_ENABLED`.
- **Kiosk crash.** Check logs: `journalctl -u framecast-kiosk -n 50`. The watchdog should auto-restart within 60 seconds.

### Photos not showing

- **Upload completed?** The web UI shows a confirmation. Check the upload page for errors.
- **File format.** Only standard image/video formats are accepted (see Configuration Reference above).
- **Disk full.** Check Settings for storage usage. Delete old photos or use a larger SD card.
- **Quarantined.** Corrupt images are automatically quarantined. Check `journalctl -u framecast` for warnings.

### OTA update failed

- **No internet.** Updates require internet access. Verify WiFi is connected.
- **SHA mismatch.** The update reports a SHA mismatch as a security check. Try again -- if it persists, report an issue.
- **Rollback.** If a bad update gets through, the health-check timer will automatically roll back within 90 seconds.

### General debugging

```bash
# Web server logs
journalctl -u framecast -n 100

# Display/kiosk logs
journalctl -u framecast-kiosk -n 50

# WiFi provisioning logs
journalctl -u wifi-manager -n 50

# System health
systemctl status framecast framecast-kiosk wifi-manager

# Firewall status
sudo ufw status
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture overview, dev setup, and PR guidelines.

## API Documentation

See [API.md](API.md) for complete endpoint documentation with request/response examples.

## Credits

Based on [pi-video-photo-slideshow](https://github.com/bobburgers7/pi-video-photo-slideshow) by bobburgers7.

## License

MIT License -- see [LICENSE](LICENSE) for details.
