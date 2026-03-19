# FrameCast Custom OS Image — Design Document

**Date:** 2026-03-19
**Status:** Approved
**Research:** `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md`

---

## Goal

Eliminate the install step. User flashes an SD card, boots the Pi, and FrameCast works — no SSH, no terminal, no `install.sh`. Distributed via GitHub Releases as a `.img.xz` file.

## Target Audience

- **Primary:** General public (download from GitHub Releases, zero technical knowledge)
- **Inner ring:** Family/friends (handed an SD card, plug and play)

## Constraints

- Pi 3/4/5 only (single 64-bit `arm64` image)
- superhot-ui for all frontend surfaces (onboarding, upload, settings, update)
- Build upstream-first: any missing superhot-ui components built there before consuming
- Green phosphor monitor variant (`data-sh-monitor="green"`) for appliance terminal aesthetic

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                 FrameCast OS Image                     │
│            (pi-gen custom stage, arm64)                │
├───────────────────────────────────────────────────────┤
│                                                        │
│  ┌───────────────────────────────┐  ┌──────────────┐  │
│  │ Flask Web App (superhot-ui)   │  │ WiFi Manager │  │
│  │                               │  │ (forked from │  │
│  │  Phone UI:     TV Display:    │  │  comitup)    │  │
│  │  - Upload      - Slideshow    │  │              │  │
│  │  - Settings    - Transitions  │  │ NetworkMgr   │  │
│  │  - Map         - Boot seq     │  │ AP+Captive   │  │
│  │  - Update      - QR codes     │  │ Portal       │  │
│  │  - Onboard     - Welcome      │  └──────────────┘  │
│  │                               │                     │
│  │  One app, two surfaces        │  ┌──────────────┐  │
│  └───────────────────────────────┘  │ OTA Updater  │  │
│                                     │ git-pull +   │  │
│  ┌───────────────┐                  │ health check │  │
│  │ Kiosk Browser │                  └──────────────┘  │
│  │ (cage +       │                                     │
│  │  GTK-WebKit)  │  ┌──────────┐                      │
│  │ Wayland, no   │  │ HW       │                      │
│  │ X11           │  │ Watchdog │                      │
│  └───────────────┘  └──────────┘                      │
└───────────────────────────────────────────────────────┘
```

**Key insight:** The slideshow IS the web app. Flask serves two surfaces from one codebase:
- **Phone** → upload, settings, map, update, onboarding (accessed via browser)
- **TV** → slideshow with CSS transitions, boot sequence, QR codes (displayed in kiosk browser)

No VLC. No mpv. No separate slideshow engine. Photo transitions are CSS animations.
Video playback via HTML5 `<video>` element.

### Systemd Services

| Service | Purpose | Type |
|---------|---------|------|
| `framecast` | Flask web app (both phone UI and TV display) | rewritten |
| `framecast-kiosk` | Kiosk browser pointed at `localhost:8080/display` | new |
| `wifi-manager` | NetworkManager WiFi provisioning (forked from comitup) | new |
| `framecast-update.timer` | OTA checker (daily, opt-in) | new |
| `watchdog` | Hardware watchdog (bcm2835_wdt) | existing |

### Display Stack

No X11. Wayland-based kiosk:
- **cage** — single-window Wayland compositor designed for kiosks (used by rpi-image-gen webkiosk example)
- **GTK-WebKit (GJS)** — lightweight browser, much less RAM than Chromium (~50MB vs ~200MB). Used by kiosk.pi.
- Auto-login on tty1 → cage → GJS browser → `http://localhost:8080/display`
- Screen blanking disabled
- Fallback: if GTK-WebKit has issues with HTML5 video on Pi, swap to Chromium in kiosk mode (heavier but proven)

### TV Display Routes

| Route | Purpose |
|-------|---------|
| `/display` | Main TV route — slideshow with transitions |
| `/display/welcome` | No-photos welcome screen with QR code |
| `/display/setup` | AP mode setup screen with QR to captive portal |
| `/display/boot` | Boot sequence animation (`bootSequence()`) |

The kiosk browser loads `/display` which auto-routes based on state:
- No WiFi → redirects to `/display/setup`
- No photos → redirects to `/display/welcome`
- Photos exist → shows slideshow (with 30s QR overlay on boot)

### Photo Transitions (CSS)

All transitions are pure CSS animations on the TV display page:

| Transition | CSS Technique |
|------------|--------------|
| Fade | `opacity` transition between stacked images |
| Slide | `transform: translateX()` with timing function |
| Zoom | `transform: scale()` — Ken Burns effect |
| None | Instant swap (for low-capability detection) |

User selects transition type in settings. `detectCapability()` auto-downgrades to simpler transitions on Pi 3.

### Open Question: HTML5 Video on Pi

HTML5 `<video>` hardware decode on Raspberry Pi via browser needs validation:
- Pi 4/5: V4L2 H.264/HEVC decode should work through Wayland
- Pi 3: May need `--enable-features=VaapiVideoDecoder` or similar flags
- If browser video is insufficient, fall back to launching mpv externally for video files only (hybrid approach)

---

## Boot Flow

```
Power on
  │
  ├─ cage starts (Wayland kiosk compositor)
  ├─ GJS/WebKit browser opens http://localhost:8080/display
  ├─ /display/boot plays bootSequence() typewriter:
  │     "FRAMECAST v1.0"
  │     "INITIALIZING..."
  │     "CHECKING NETWORK..."
  │
  ├─ WiFi configured?
  │   ├─ NO → /display/setup:
  │   │       bootSequence() continues:
  │   │         "NO NETWORK CONFIGURED"
  │   │         "SETUP REQUIRED"
  │   │       QR code → http://192.168.4.1:8080
  │   │       "CONNECT TO WIFI: FrameCast-XXXX"
  │   │       [persistent until WiFi configured]
  │   │       [Flask serves captive portal on same port]
  │   │
  │   └─ YES → Photos exist?
  │       ├─ NO → /display/welcome:
  │       │       QR code → http://framecast.local:8080
  │       │       "AWAITING INPUT" mantra
  │       │       [persistent until photos uploaded]
  │       │       [auto-refreshes when first photo lands]
  │       │
  │       └─ YES → /display (slideshow):
  │               QR overlay for 30s (configurable)
  │               then → slideshow with CSS transitions
  │               [WebSocket push updates when new photos uploaded]
```

The 30-second QR on reboot is a safety net — family members who need to add more photos catch it after any power cycle.

The `/display` route uses WebSocket (or SSE) from Flask to react in real-time:
- New photo uploaded → slideshow adds it without page reload
- Settings changed (transition type, duration) → applies immediately
- WiFi lost → transitions to `/display/setup` automatically

---

## WiFi Provisioning

**Dual-path approach:**

### Path 1: Hotspot + Captive Portal (primary, for everyone)

Fork comitup's NetworkManager-based WiFi provisioning logic:
- On first boot (or when no known networks available), Pi creates AP: `FrameCast-XXXX`
- Phone connects → captive portal redirect → Flask serves superhot-ui onboarding wizard
- Wizard flow: SCAN → SELECT → CONNECT → DONE (`.sh-progress-steps`)
- Network list shows `.sh-signal-bars` for each SSID
- Password entry via `.sh-input`
- On success: AP shuts down, Pi joins selected network

### Path 2: Boot Partition File (power users)

Create `framecast-wifi.txt` on SD card's FAT32 boot partition before first boot:
```
SSID=MyNetwork
PASSWORD=MyPassword
```
Pi reads this on first boot, connects, deletes the file.

---

## Web UI (superhot-ui)

All surfaces served by Flask, rendered with Preact + superhot-ui.
Green phosphor monitor variant (`data-sh-monitor="green"`).
`detectCapability()` at init — auto-downgrade effects on Pi 3.

### Pages

**1. Onboarding Wizard** (`/setup`)
- `bootSequence()` welcome text
- `.sh-progress-steps`: SCAN → SELECT → CONNECT → DONE
- `.sh-signal-bars` for network list
- `.sh-input` for password, `.sh-frame` for step containers
- `ShModal` for confirmations, `ShToast` for results

**2. Upload** (`/` — main page)
- `.sh-dropzone` (built in FrameCast, not superhot-ui)
  - Idle: dashed phosphor border, `.sh-mantra` watermark "AWAITING INPUT"
  - Drag-over: solid phosphor + glow
  - Receiving: `.sh-progress` ASCII bar inside
  - Error: threat border
  - Complete: glitch burst + `ShToast` — NO shatter (shatter = destroyed)
- Photo grid with thumbnails
- `ShToast` for upload success/failure: `[UPLOAD] RECEIVED: photo.jpg`

**3. Settings** (`/settings`)
- `.sh-frame` groups: DISPLAY, NETWORK, SYSTEM
- `.sh-toggle` for: auto-update, HDMI schedule, SSH
- `.sh-input` for: hostname, schedule times
- `.sh-select` for: slideshow interval, transition type
- `ShCollapsible` for ADVANCED section
- QR display duration (default 30s)

**4. Update** (`/update`)
- `.sh-progress-steps`: DOWNLOAD → INSTALL → VERIFY → REBOOT
- `.sh-progress` ASCII bar for download
- `ShToast` for result
- `bootSequence()` post-update restart animation

### Typography (piOS discipline throughout)

- Labels: `UPPERCASE`, monospace, muted
- Status: lowercase monospace codes (`healthy`, `error`)
- System messages: `[WIFI] CONNECTED`, `[UPLOAD] RECEIVED`, `AWAITING INPUT`
- Empty states: `NO ACTIVE PHOTOS`, `STANDBY`, `OFFLINE`
- No prose, no apologies, no "Please wait..."

---

## OTA Update System

### Web UI Button (primary)
User clicks "CHECK FOR UPDATES" on settings/update page.

### Opt-in Auto-Update
- `framecast-update.timer` — daily check at 3:00 AM (configurable)
- Disabled by default, enabled via settings toggle
- Checks GitHub Releases API for newer tags

### Update Flow
1. Compare local version tag vs. latest GitHub Release
2. If newer: `git fetch && git checkout <tag>`
3. Re-run install steps (apt is pre-baked, only app files change)
4. Reboot

### Rollback (health check + git revert)
After update + reboot:
1. 90-second watchdog timer starts
2. Check: are `slideshow` and `photo-upload` services both `active`?
3. If YES → update confirmed, clear rollback state
4. If NO → `git checkout <previous-tag>`, re-install, reboot
5. Failure mode: "frame shows old version" not "frame is bricked"

---

## Pi-Gen Build

### Stage Structure

```
stage2-framecast/
  prerun.sh                      # copy_previous
  EXPORT_IMAGE                   # triggers .img export
  00-packages/
    00-packages                  # cage, gjs, gir1.2-webkit2-4.0,
                                 # python3-flask, ffmpeg, watchdog,
                                 # qrencode, avahi-daemon, network-manager,
                                 # python3-pil, python3-pip, nodejs (for esbuild)
  01-config/
    01-run.sh                    # boot config, display settings, watchdog
    files/
      config.txt                 # GPU mem (Pi 3), disable splash
      cmdline.txt                # quiet boot
  02-app/
    01-run.sh                    # copy app files, build frontend (npm run build)
    01-run-chroot.sh             # enable services, create user, sudoers
    files/
      framecast.service          # Flask web app
      framecast-kiosk.service    # cage + GJS browser → localhost:8080/display
      wifi-manager.service
      framecast-update.timer
      framecast-update.service
  03-system/
    01-run.sh                    # SD card longevity (journal, tmpfs, noatime)
    files/
      kiosk.sh                   # cage → GJS browser fullscreen
      kiosk-browser.js           # GJS/WebKit browser script
      pi-photo-display.conf      # journald limits
```

### Build Config

```
IMG_NAME="FrameCast"
RELEASE="bookworm"
TARGET_HOSTNAME="framecast"
FIRST_USER_NAME="pi"
FIRST_USER_PASS="framecast"
ENABLE_SSH=0
LOCALE_DEFAULT="en_US.UTF-8"
KEYBOARD_KEYMAP="us"
TIMEZONE_DEFAULT="UTC"
STAGE_LIST="stage0 stage1 stage2 stage2-framecast"
```

### Build Method
- Docker-based (`build-docker.sh`) for reproducibility
- GitHub Actions CI on release tags → publish `.img.xz` to Releases
- Build host: any Linux x86_64 with Docker (10-20GB disk, 20-60min)

---

## GitHub Best Practices & Scaffolding

### Repository Structure

```
framecast/
├── .github/
│   ├── workflows/
│   │   ├── build-image.yml      # pi-gen build on release tags
│   │   ├── test.yml              # smoke tests on PR
│   │   └── release.yml           # publish .img.xz to Releases
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml        # structured bug template
│   │   └── feature_request.yml   # feature request template
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── FUNDING.yml               # if applicable
├── app/                           # Flask web app (existing, rewritten)
│   ├── static/                    # superhot-ui dist, built frontend assets
│   ├── templates/                 # Jinja2 templates (minimal — Preact SPA)
│   ├── modules/                   # Python modules
│   │   ├── config.py              # existing
│   │   ├── media.py               # existing (GPS, locations, file management)
│   │   ├── services.py            # existing
│   │   ├── wifi.py                # NetworkManager WiFi provisioning (from comitup)
│   │   └── updater.py             # OTA update logic
│   ├── frontend/                  # Preact + superhot-ui source (esbuild)
│   │   ├── src/
│   │   │   ├── pages/
│   │   │   │   ├── Upload.jsx     # Photo upload with ShDropzone
│   │   │   │   ├── Settings.jsx   # All settings
│   │   │   │   ├── Map.jsx        # Photo map (Leaflet + GPS)
│   │   │   │   ├── Update.jsx     # OTA update UI
│   │   │   │   └── Onboard.jsx    # WiFi setup wizard
│   │   │   ├── display/           # TV display pages (kiosk browser)
│   │   │   │   ├── Slideshow.jsx  # Photo slideshow with CSS transitions
│   │   │   │   ├── Welcome.jsx    # No-photos QR screen
│   │   │   │   ├── Setup.jsx      # AP mode QR screen
│   │   │   │   └── Boot.jsx       # bootSequence() animation
│   │   │   ├── components/        # ShDropzone, WiFiList, PhotoGrid, QRCode
│   │   │   └── app.jsx            # Router + ShNav (phone) / display router (TV)
│   │   ├── package.json
│   │   └── esbuild.config.js
│   ├── web_upload.py              # Flask routes (phone + TV display)
│   └── .env.example
├── kiosk/                         # Kiosk browser scripts
│   ├── kiosk.sh                   # cage → GJS browser
│   └── browser.js                 # GJS/WebKit fullscreen browser
├── pi-gen/                        # pi-gen build config
│   ├── config                     # IMG_NAME, STAGE_LIST, etc.
│   ├── stage2-framecast/          # custom stage
│   └── build.sh                   # wrapper around pi-gen build-docker.sh
├── scripts/
│   ├── smoke-test.sh              # existing
│   └── health-check.sh            # post-update rollback check
├── systemd/                       # service/timer definitions
│   ├── framecast.service          # Flask web app
│   ├── framecast-kiosk.service    # cage + GJS browser
│   ├── wifi-manager.service       # WiFi provisioning
│   ├── framecast-update.service   # OTA updater
│   └── framecast-update.timer     # daily update check
├── docs/
│   └── plans/                     # design docs, research
├── install.sh                     # kept for dev/manual install
├── Makefile                       # existing + new targets
├── CLAUDE.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE
├── VERSION
└── README.md
```

### GitHub Scaffolding

**Issue templates** — structured YAML forms for bugs (Pi model, OS version, symptoms, logs) and feature requests.

**PR template** — checklist: tests pass, smoke test on real Pi, CHANGELOG updated, no secrets.

**Branch protection on `main`:**
- Require PR reviews
- Require status checks (test workflow)
- No direct pushes

**GitHub Actions workflows:**
1. **test.yml** — on PR: lint, unit tests, smoke test (can run without Pi hardware)
2. **build-image.yml** — on release tag: run pi-gen Docker build, produce `.img.xz`
3. **release.yml** — on build success: create GitHub Release, attach image, generate release notes

**Releases:**
- Semantic versioning (`v1.0.0`, `v1.1.0`)
- Each release has: `.img.xz` image, SHA256 checksum, release notes
- README links to latest release with flash instructions

**Labels:** `bug`, `enhancement`, `pi3`, `pi4`, `pi5`, `wifi`, `display`, `update-system`, `good first issue`

---

## Superhot-UI Component Mapping

All validated against four tests (One Signal, Diegetic, Three-Color, Emotional Loop).

| Component | Usage | Status |
|-----------|-------|--------|
| `.sh-progress-steps` | Onboarding wizard, update stages | existing |
| `.sh-signal-bars` | WiFi network list | existing |
| `.sh-input` / `.sh-select` / `.sh-toggle` | Forms throughout | existing |
| `.sh-frame` | Section containers | existing |
| `.sh-progress` | Upload + download progress | existing |
| `ShModal` | Confirmation dialogs | existing |
| `ShToast` | All notifications | existing |
| `ShCollapsible` | Advanced settings | existing |
| `ShNav` | Page navigation | existing |
| `bootSequence()` | First-boot welcome, post-update | existing |
| `detectCapability()` | Pi hardware auto-downgrade | existing |
| `.sh-dropzone` | Photo upload drag-and-drop | **build in FrameCast** |

### Dropzone Design (FrameCast-local)

Built in FrameCast, not superhot-ui. Extract upstream if reuse materializes.

States via `data-sh-dropzone` attribute:
- `idle` — dashed phosphor border, `.sh-mantra` watermark "AWAITING INPUT"
- `hover` — solid phosphor border + glow
- `receiving` — solid phosphor, `.sh-progress` bar inside
- `error` — threat border + glow
- `complete` — phosphor flash, glitch burst on thumbnail, toast notification

---

## Slideshow Engine (Browser-Based)

The slideshow is a Preact SPA page (`/display`) running in the kiosk browser. No VLC, no mpv.

### How It Works

1. Flask serves `/display` → Preact app loads photo list via `/api/photos`
2. Two `<img>` elements stacked (current + next), CSS transition between them
3. WebSocket/SSE from Flask pushes events: new photo, deleted photo, settings change
4. Timer advances photos at configured interval (`PHOTO_DURATION`)
5. Video files play via HTML5 `<video>` with `autoplay muted` (unmuted if only video)

### Transition Implementation

```
┌──────────────────────────┐
│ .slideshow-container      │
│ ┌──────────────────────┐ │
│ │ img.current (z: 2)   │ │  ← visible photo
│ │ opacity: 1            │ │
│ ├──────────────────────┤ │
│ │ img.next (z: 1)      │ │  ← preloaded next photo
│ │ opacity: 0            │ │
│ └──────────────────────┘ │
└──────────────────────────┘

On advance:
  1. Set next.src = photos[i+1], preload
  2. Apply transition class to current (e.g. .fade-out)
  3. Apply transition class to next (e.g. .fade-in)
  4. On transitionend: swap z-index, reset classes
```

| Transition | CSS | Emotional Fit |
|------------|-----|---------------|
| Fade | `opacity 0→1 / 1→0` over 1.5s ease | Calm, default |
| Slide | `translateX(100%) → 0` | Motion, energy |
| Ken Burns | `scale(1) → scale(1.1)` + slow pan | Cinematic, photos |
| Dissolve | Crossfade with slight blur | Soft, dreamy |
| None | Instant swap | Low-capability fallback |

### Real-Time Updates

Flask → browser communication via WebSocket (flask-socketio or SSE):
- `photo:added` → insert into rotation, preload
- `photo:deleted` → remove from rotation, skip if current
- `settings:changed` → apply new duration/transition immediately
- `wifi:lost` → show setup screen
- `update:rebooting` → show boot sequence

### QR Code Overlay

On boot with photos present: 30s overlay at bottom-right showing QR code to web UI.
Generated client-side using a JS QR library (qrcode.js) — no server-side qrencode needed for the display.
Server-side qrencode still used for the static welcome images (no-WiFi and no-photos states).

---

## v2 Backlog

Captured for next iteration — not in v1 scope:

1. **HDMI-CEC** — wake/sleep TV via CEC commands instead of just blanking HDMI. kiosk.pi has a `cec2kbd` implementation to reference.
2. **Read-only overlay FS** — `raspi-config nonint enable_overlayfs` on first boot. Protects SD card from power-pull corruption. Requires writable data partition for media + config.
3. **Timezone/locale auto-detect** — use browser `Intl.DateTimeFormat().resolvedOptions().timeZone` during onboarding to set Pi timezone. Manual override in settings.
4. **SSH toggle** — disabled by default for security. Settings page toggle to enable. Requires `systemctl enable/start ssh` from web UI.
5. **Unique hostname** — append last 4 of MAC address (`framecast-a1b2.local`) to avoid mDNS collision with multiple frames.
6. **Photo management** — reorder, albums, favorites. v1 is upload + delete only.
7. **Multiple frame discovery** — if a household has 2+ frames, the web UI could show a "FRAMES" page listing all discovered frames via mDNS.
8. **HDMI-CEC remote control** — map TV remote buttons to slideshow controls (pause, next, previous) via `cec-utils`.
9. **Auto-update rollback logging** — write rollback events to persistent log for debugging.
10. **HTML5 video hardware decode validation** — verify H.264/HEVC hardware decode through GTK-WebKit on Pi 3/4/5 via Wayland. If insufficient, hybrid approach: browser for photos, launch mpv externally for video files only.

---

## Reference

- **pi-gen research:** `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md`
- **kiosk.pi (cleanest pi-gen ref):** https://github.com/deltazero-cz/kiosk.pi
- **mrworf/photoframe (pi-gen + OTA):** https://github.com/mrworf/photoframe
- **comitup (WiFi provisioning):** https://github.com/davesteele/comitup
- **superhot-ui design philosophy:** `~/Documents/projects/superhot-ui/docs/design-philosophy.md`
- **superhot-ui consumer guide:** `~/Documents/projects/superhot-ui/docs/consumer-guide.md`
