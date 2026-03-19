# FrameCast

**Turn any TV into a family photo frame -- flash, boot, done.**

FrameCast is a ready-to-flash OS image for Raspberry Pi. Download the image, write it to an SD card, plug the Pi into your TV, and you have a photo frame. No SSH, no terminal, no Linux knowledge required.

Anyone on your WiFi can upload photos from their phone's browser. No app, no cloud, no subscription.

---

## Quick Start

1. **Download** the latest `.img.xz` from [Releases](../../releases)
2. **Flash** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (select "Use custom" and pick the downloaded file)
3. **Boot** the Pi -- it displays a setup screen with a QR code
4. **Connect** to the `FrameCast` WiFi network shown on screen
5. **Upload** photos at the address shown (scan the QR code or type it in)

That's it. Photos appear on the TV within seconds.

---

## Features

- **Browser-based slideshow** with CSS transitions (fade, slide, Ken Burns)
- **superhot-ui terminal aesthetic** -- green phosphor interface
- **WiFi captive portal** with onboarding wizard -- no SSH needed
- **Drag-and-drop upload** from any phone, tablet, or computer
- **Photo map** plotting GPS EXIF data on an offline SVG world map
- **Server-Sent Events** for real-time display updates
- **OTA updates** with health-check rollback
- **PIN authentication** for the web UI
- **HDMI schedule** to turn the display off at night
- **Wayland kiosk** (cage + GTK-WebKit) -- no X11
- **Self-healing** -- crash recovery, hardware watchdog, config restore
- **WiFi hotspot fallback** when your home network is unavailable

---

## Supported Hardware

| Pi Model | Status |
|----------|--------|
| Raspberry Pi 3B / 3B+ | Supported (64-bit) |
| Raspberry Pi 4 | Supported (64-bit) |
| Raspberry Pi 5 | Supported (64-bit) |

Any HDMI TV or monitor works. A small 7" or 10" HDMI display works well as a dedicated frame.

**Requirements:** microSD card (16 GB minimum, 32 GB recommended), power supply for your Pi model, HDMI cable (micro-HDMI adapter for Pi 4/5).

---

## How It Works

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
|             |   ~/media/     |                 |
|             | photos & videos|                 |
|             +----------------+                 |
|                                                |
|  systemd services | watchdog | OTA updater     |
+-------------------------------------------------+
                      | HDMI
                      v
              +---------------+
              |  TV / Monitor |
              +---------------+
```

Wayland only — no X11. The kiosk browser (`cage` compositor + `GTK-WebKit`) renders the slideshow page served by the same Flask app.

---

## Settings

Once running, open the web UI and navigate to Settings to configure:

- Photo duration, shuffle, loop mode
- Slideshow transitions (fade, slide, Ken Burns)
- HDMI on/off schedule
- Upload size limits
- PIN protection
- WiFi network (via captive portal)
- OTA updates

---

## For Developers

### Building from Source

```bash
git clone https://github.com/parthalon025/framecast.git
cd framecast
```

```bash
# Build the frontend (requires Node.js 18+)
cd app/frontend && npm ci && npm run build && cd ../..
```

```bash
# Run locally for UI development
cd app && gunicorn -c gunicorn.conf.py web_upload:app
```

### Building the OS Image

The image is built with [pi-gen](https://github.com/RPi-Distro/pi-gen) in Docker:

```bash
cd pi-gen
bash build.sh
```

This clones pi-gen, applies the FrameCast stage, and produces a `.img.xz` in `pi-gen/deploy/`. Takes 20-60 minutes depending on your machine.

### Project Structure

```
framecast/
|-- app/
|   |-- web_upload.py              # Flask web server
|   |-- api.py                     # REST API endpoints
|   |-- sse.py                     # Server-Sent Events
|   |-- gunicorn.conf.py           # Gunicorn configuration
|   |-- modules/                   # Python modules (config, media, auth, wifi, etc.)
|   |-- frontend/                  # Preact SPA (superhot-ui)
|   |   |-- src/                   # JSX components and pages
|   |   |-- esbuild.config.js      # Build configuration
|   |-- static/                    # Built CSS/JS assets
|   |-- templates/                 # HTML templates
|-- pi-gen/
|   |-- build.sh                   # Image build script
|   |-- config                     # pi-gen configuration
|   |-- stage2-framecast/          # Custom pi-gen stage
|-- scripts/
|   |-- smoke-test.sh              # Post-install validation
|-- systemd/                       # Service definitions
|-- install.sh                     # One-command Pi installer
|-- VERSION                        # Current version
```

### CI/CD

- **Pull requests** trigger lint (ruff) and frontend build checks
- **Tag pushes** (`v*`) build the OS image via pi-gen Docker
- **Releases** are created automatically with the image and SHA256 checksum

---

## Credits

Based on [pi-video-photo-slideshow](https://github.com/bobburgers7/pi-video-photo-slideshow) by bobburgers7.

## License

MIT License -- see [LICENSE](LICENSE) for details.
