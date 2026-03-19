# FrameCast

Turn any TV into a family photo frame — flash an SD card, boot the Pi, done. Browser-based slideshow with CSS transitions, superhot-ui terminal interface, WiFi captive portal, OTA updates.

## Stack

- Python (Flask + gunicorn), SSE for real-time updates
- Preact + esbuild + superhot-ui (green phosphor monitor variant)
- Wayland kiosk (cage + GTK-WebKit, no X11)
- NetworkManager (nmcli) for WiFi provisioning
- pi-gen for OS image builds
- GitHub Actions CI/CD

## Architecture

One Flask app serves two surfaces:
- **Phone** → upload, settings, map, update, onboarding (Preact SPA)
- **TV** → slideshow with CSS transitions, boot sequence, QR codes (kiosk browser)

No VLC. No mpv. Slideshow is a Preact page with CSS animations.

## Key Directories

| Path | Purpose |
|------|---------|
| `app/` | Flask web app (routes, modules, templates) |
| `app/frontend/` | Preact + superhot-ui source (esbuild) |
| `app/modules/` | Python modules (config, media, wifi, updater, auth) |
| `kiosk/` | GJS/WebKit browser + cage launcher |
| `pi-gen/` | Custom pi-gen stage for OS image build |
| `systemd/` | Service and timer definitions |
| `scripts/` | Health check, HDMI control, smoke tests |
| `docs/plans/` | Design docs and research |

## Services

| Service | Purpose |
|---------|---------|
| `framecast` | gunicorn + Flask (phone UI + TV display) |
| `framecast-kiosk` | cage + GTK-WebKit → localhost:8080/display |
| `wifi-manager` | NetworkManager WiFi provisioning |
| `framecast-update.timer` | OTA update checker (daily, opt-in) |

## Build

- Frontend: `cd app/frontend && npm install && npm run build`
- Image: `cd pi-gen && bash build.sh` (Docker, 20-60min)
- Dev: `cd app && gunicorn -c gunicorn.conf.py web_upload:app`

## Conventions

- Target: Raspberry Pi 3/4/5 (arm64, Bookworm)
- Display: Browser-based slideshow with CSS transitions (fade, slide, Ken Burns)
- Network: WiFi captive portal (AP mode) + boot partition config file
- Upload: Drag-and-drop from phone via superhot-ui ShDropzone
- Auth: Optional 4-digit PIN displayed on TV screen
- Updates: OTA via GitHub Releases API with health-check rollback
- Media: JPG, PNG, GIF, WEBP, TIFF, MP4, MKV, AVI, MOV
- Frontend: superhot-ui with green phosphor variant, piOS typography (UPPERCASE labels, terse status codes)
- NEVER use `h` as a callback parameter name in JSX (esbuild shadows)

## Design Docs

- `docs/plans/2026-03-19-framecast-image-design.md` — Full design document
- `docs/plans/2026-03-19-framecast-image-plan.md` — Implementation plan (12 batches)
- `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md` — Pi-gen research
- `docs/plans/2026-03-19-mpv-vs-vlc-display-stack-research.md` — Display stack research
