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
┌─────────────────────────────────────────────────┐
│              FrameCast OS Image                  │
│         (pi-gen custom stage, arm64)             │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ VLC      │  │ Flask    │  │ WiFi Manager │  │
│  │ Slideshow│  │ Web App  │  │ (forked from │  │
│  │          │  │ (superhot│  │  comitup)    │  │
│  │ systemd  │  │  -ui)    │  │              │  │
│  │ service  │  │          │  │ NetworkMgr   │  │
│  └──────────┘  │ Upload   │  │ AP+Captive   │  │
│                │ Settings │  │ Portal       │  │
│  ┌──────────┐  │ Update   │  └──────────────┘  │
│  │ Openbox  │  │ Onboard  │                     │
│  │ (minimal │  └──────────┘  ┌──────────────┐  │
│  │  X11)    │                │ OTA Updater  │  │
│  └──────────┘                │ git-pull +   │  │
│                              │ health check │  │
│  ┌──────────┐                └──────────────┘  │
│  │ HW       │                                   │
│  │ Watchdog │                                   │
│  └──────────┘                                   │
└─────────────────────────────────────────────────┘
```

### Systemd Services

| Service | Purpose | Type |
|---------|---------|------|
| `slideshow` | VLC fullscreen on X11/openbox | existing, unchanged |
| `photo-upload` | Flask web app (superhot-ui frontend) | rewritten |
| `wifi-manager` | NetworkManager WiFi provisioning (forked from comitup) | new |
| `framecast-update.timer` | OTA checker (daily, opt-in) | new |
| `watchdog` | Hardware watchdog (bcm2835_wdt) | existing |

### Display Stack

Minimal X11 — no desktop environment:
- Openbox window manager (lightest WM with EWMH compliance for VLC)
- Auto-login on tty1 → `startx` → `.xinitrc` → openbox → VLC
- No LightDM, no LXDE, no taskbar
- Screen blanking disabled

---

## Boot Flow

```
Power on
  │
  ├─ openbox starts (minimal X11)
  ├─ VLC slideshow service starts
  │
  ├─ WiFi configured?
  │   ├─ NO → AP mode ("FrameCast-XXXX")
  │   │       TV shows welcome screen:
  │   │         bootSequence() typewriter:
  │   │           "FRAMECAST v1.0"
  │   │           "NO NETWORK CONFIGURED"
  │   │           "SETUP REQUIRED"
  │   │         QR code → http://192.168.4.1:8080
  │   │         "CONNECT TO WIFI: FrameCast-XXXX"
  │   │       [persistent until WiFi configured]
  │   │
  │   └─ YES → Photos exist?
  │       ├─ NO → Welcome screen:
  │       │       QR code → http://framecast.local:8080
  │       │       "AWAITING INPUT" mantra
  │       │       [persistent until photos uploaded]
  │       │
  │       └─ YES → QR overlay for 30s (configurable)
  │               then → normal slideshow
```

The 30-second QR on reboot is a safety net — family members who need to add more photos catch it after any power cycle.

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
    00-packages                  # vlc, openbox, python3-flask, ffmpeg,
                                 # xdotool, watchdog, qrencode, avahi-daemon,
                                 # network-manager, python3-pil, python3-pip
  01-config/
    01-run.sh                    # boot config, display settings, watchdog
    files/
      config.txt                 # GPU mem (Pi 3), disable splash
      cmdline.txt                # quiet boot
  02-app/
    01-run.sh                    # copy app files, install npm deps
    01-run-chroot.sh             # enable services, create user, sudoers
    files/
      slideshow.service
      photo-upload.service
      wifi-manager.service
      framecast-update.timer
      framecast-update.service
  03-system/
    01-run.sh                    # SD card longevity (journal, tmpfs, noatime)
    files/
      .xinitrc                   # openbox → VLC
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
│   ├── static/                    # superhot-ui dist, assets
│   ├── templates/                 # Jinja2 templates
│   ├── modules/                   # Python modules
│   ├── frontend/                  # Preact source (esbuild)
│   │   ├── src/
│   │   │   ├── pages/             # Onboard, Upload, Settings, Update
│   │   │   ├── components/        # ShDropzone, WiFiList, PhotoGrid
│   │   │   └── app.jsx            # Router + ShNav
│   │   ├── package.json
│   │   └── esbuild.config.js
│   ├── web_upload.py              # Flask routes
│   ├── wifi_manager.py            # NetworkManager WiFi provisioning
│   ├── updater.py                 # OTA update logic
│   ├── slideshow.sh               # existing
│   └── .env.example
├── pi-gen/                        # pi-gen build config
│   ├── config                     # IMG_NAME, STAGE_LIST, etc.
│   ├── stage2-framecast/          # custom stage
│   └── build.sh                   # wrapper around pi-gen build-docker.sh
├── scripts/
│   ├── smoke-test.sh              # existing
│   └── health-check.sh            # post-update rollback check
├── systemd/                       # service/timer definitions
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

---

## Reference

- **pi-gen research:** `docs/plans/2026-03-19-pi-gen-photo-frame-kiosk-research.md`
- **kiosk.pi (cleanest pi-gen ref):** https://github.com/deltazero-cz/kiosk.pi
- **mrworf/photoframe (pi-gen + OTA):** https://github.com/mrworf/photoframe
- **comitup (WiFi provisioning):** https://github.com/davesteele/comitup
- **superhot-ui design philosophy:** `~/Documents/projects/superhot-ui/docs/design-philosophy.md`
- **superhot-ui consumer guide:** `~/Documents/projects/superhot-ui/docs/consumer-guide.md`
