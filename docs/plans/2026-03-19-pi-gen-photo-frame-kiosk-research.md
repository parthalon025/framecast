# Pi-Gen Photo Frame & Kiosk Image Research

**Date:** 2026-03-19
**Purpose:** Survey existing open-source projects that use pi-gen (or equivalent) to build custom Raspberry Pi images for photo frames and kiosks. Extract architecture patterns, WiFi provisioning, OTA update strategies, and known failure modes.

---

## Top 3 Repos

### 1. deltazero-cz/kiosk.pi

**URL:** https://github.com/deltazero-cz/kiosk.pi
**Stars:** 27 | **Forks:** 6 | **Language:** Shell | **Last updated:** 2025-10-20

The most directly relevant project. A clean, minimal pi-gen fork that adds a single custom stage (`stage2-kiosk`) to build a web kiosk image.

**Architecture:**
- Clones upstream pi-gen, symlinks its `config` and `stage2-kiosk` into the clone, then runs `build.sh`.
- Uses `STAGE_LIST="stage0 stage1 stage2 stage2-kiosk"` -- skips stages 3-5 (no desktop, no bloat).
- Disables image export from stage2 (`SKIP_IMAGES`, `SKIP_NOOBS`), only exports from `stage2-kiosk`.
- `stage2-kiosk/prerun.sh` calls `copy_previous` to inherit stage2's rootfs.

**Custom Stage Structure (`stage2-kiosk/00-kiosk/`):**
```
00-packages          # xorg, x11-xserver-utils, feh, gjs, gir1.2-webkit2-4.0, cec-utils, xdotool, vim
01-run.sh            # Installs files, sets up user, writes kiosk URL to /boot/kiosk.url
files/
  .profile           # Auto-runs firstrun.sh on first login, then `startx` on tty1
  .xinitrc            # Runs kiosk.sh
  .hushlogin          # Suppresses login banner
  kiosk.sh            # Reads URL from /boot/kiosk.url, disables screensaver, launches browser
  firstrun.sh         # Enables read-only overlay FS, removes itself, reboots
  bin/browser          # GJS/GTK-WebKit fullscreen browser (NOT Chromium -- lighter weight)
  bin/cec2kbd          # Translates HDMI-CEC remote signals to keyboard events
  config.txt          # Custom boot config (GPU memory, disable splash, disable BT)
  cmdline.txt         # Quiet boot
  splash.png           # Boot splash image
EXPORT_IMAGE          # Triggers image export for this stage
```

**Key Design Decisions:**
- Uses GTK-WebKit via GJS instead of Chromium -- dramatically lighter on memory/CPU
- First-boot script enables `raspi-config nonint enable_overlayfs` (read-only root) -- protects against SD card corruption from power loss
- URL is configured via `/boot/kiosk.url` (editable on the FAT32 boot partition from any OS)
- CEC integration translates TV remote → keyboard events
- Auto-login on tty1 → startx → .xinitrc → kiosk.sh

**WiFi Configuration:** Pre-baked in `config` via `WPA_ESSID` and `WPA_PASSWORD`. No captive portal or first-boot WiFi provisioning. WiFi must be known at image build time or edited on SD card boot partition.

**OTA Updates:** None. The read-only overlay FS makes this impossible without disabling it first. This is a deploy-once-and-forget design.

**Known Limitations:**
- No issues filed on the repo (too small a community)
- Pinned to Bullseye (not Bookworm) -- may need updating for Pi 5
- No dynamic WiFi provisioning
- Read-only FS prevents updates without re-flashing
- WebKit renderer is less capable than Chromium for complex web apps

---

### 2. mrworf/photoframe (+ mrworf/pi-gen photoframe branch)

**URL:** https://github.com/mrworf/photoframe
**Pi-gen fork:** https://github.com/mrworf/pi-gen/tree/photoframe
**Stars:** 237 | **Forks:** 39 | **Language:** Python | **Last updated:** 2026-03-12

A full-featured photo frame application with a dedicated pi-gen branch for image building.

**Architecture:**
- Forks the full pi-gen repo. Adds `stage2/03-photoframe/` as a substage within stage2 (not a separate stage).
- Skips stages 3-5 (SKIP files present) -- builds Lite image + photoframe customizations.
- Config: `IMG_NAME='PHOTOFRAME'`, `PHOTOFRAME_BRANCH=master` (configurable via `config.local`).

**Custom Substage Structure (`stage2/03-photoframe/`):**
```
00-packages          # git, python, python-requests, python-flask, imagemagick, fbset, rng-tools, openssh-server
00-patches/          # (present but contents not inspected)
01-run.sh            # Main install script
files/
  fix_wifi.sh        # WiFi watchdog -- loops checking ESSID, restarts networking + kills wpa_supplicant if disconnected
  fixwifi.service    # systemd unit for the WiFi watchdog
  http-auth.json     # Default HTTP auth credentials installed to /boot/
  colortemp_info.txt # Color temperature reference data
```

**01-run.sh Key Operations:**
1. Disables `getty@tty1` and masks `plymouth-start` (no console, no splash animation)
2. Creates `/root/photoframe_config/`
3. Clones the photoframe repo into `/root/photoframe/` (or copies from local source if `PHOTOFRAME_SRC` is set)
4. Enables `frame.service` (systemd unit from the cloned repo)
5. Enables `fixwifi.service` (WiFi watchdog)
6. Adds cron entry: `15 3 * * *` runs `/root/photoframe/update.sh` -- **daily git pull for OTA**

**WiFi Configuration:**
- Standard `wifi-config.txt` on boot partition (edit before first boot)
- WiFi watchdog daemon (`fix_wifi.sh`) loops every 30s checking `iwconfig wlan0` for `ESSID:off/any`. If disconnected, restarts networking; if that fails, kills `wpa_supplicant` and retries.
- No captive portal -- manual config only.

**OTA Updates:**
- Cron-based git pull: `/root/photoframe/update.sh` runs daily at 3:15 AM
- Caveat: modifying files in `/root/photoframe/` breaks auto-update (git pull conflicts)
- This is application-level OTA only -- OS is not updated

**Known Limitations / Issues (from GitHub issues):**
- **Google Photos API is dead** -- the primary use case (Google Photos integration) is broken due to API changes (March 2025). Pexels and USB still work.
- Multiple auth/authorization failures reported in issues
- Python 2 legacy (migration to Python 3 in progress)
- SPI display color inversion issues
- Certificate verification errors ("bad handshake")
- WiFi watchdog is a brute-force workaround for wpa_supplicant instability

---

### 3. jareware/chilipie-kiosk

**URL:** https://github.com/jareware/chilipie-kiosk
**Stars:** 1,397 | **Forks:** 156 | **Language:** HTML | **Last updated:** 2026-03-12

The most popular Pi kiosk project. Does NOT use pi-gen -- builds images via an interactive SSH-based script that configures a running Pi, then dd's the SD card.

**Architecture:**
- Starts from stock Raspberry Pi OS Lite flashed via Raspberry Pi Imager
- `docs/image-setup.sh` is a lengthy interactive script that SSHs into the Pi and configures it step by step
- Build process: flash Lite → boot Pi on Ethernet → SSH in → configure → resize partition → install packages → copy home files → dd image off SD card
- Uses Matchbox window manager + Chromium in kiosk mode
- Auto-login on tty1/2/3 → `.bash_profile` → `.xsession` (starts X + Chromium)

**Key Home Directory Files:**
```
.bash_profile        # Starts X session
.xsession            # Launches Chromium with kiosk flags
.chilipie-kiosk-version  # Version tracking
background.png       # Boot splash
first-boot.html      # Welcome page displayed on first boot
cec-off.sh / cec-on.sh   # HDMI-CEC display power control
display-off.sh / display-on.sh  # Display power management
crontab.example      # Nightly reboot, page refresh, tab cycling
```

**WiFi Configuration:**
- Pre-boot: create `wpa_supplicant.conf` on the boot partition before first power-on
- Post-boot: `raspi-config` via `Ctrl+Alt+F2` virtual terminal
- No captive portal

**OTA Updates:**
- **Explicitly disabled.** "No automatic updates" is a listed feature. Chrome and system packages do not auto-update. The philosophy is stability for unattended operation.

**Known Limitations (from issues):**
- "Device unusable after some days" (resource exhaustion from Chromium)
- Chromium memory leaks on long-running kiosks
- No multi-display support (single HDMI only)
- TV displays may not power on/off via HDMI signal (CEC compatibility varies)
- Power supply sensitivity (must be 2.5A+, "rainbow square" / "yellow lightning" if insufficient)
- SD card compatibility issues
- Not built with pi-gen -- harder to reproduce/customize/CI

---

## Comparison Matrix

| Feature | kiosk.pi | mrworf/photoframe | chilipie-kiosk |
|---|---|---|---|
| **Build system** | pi-gen (custom stage) | pi-gen (fork, custom substage) | Interactive SSH script |
| **Base** | Stage 0-2 + custom | Stage 0-2 + custom | Raspberry Pi OS Lite |
| **Display engine** | GTK-WebKit (GJS) | Python + framebuffer (fbset, imagemagick) | Chromium + Matchbox WM |
| **WiFi provisioning** | Build-time config only | Boot partition file + watchdog | Boot partition wpa_supplicant |
| **WiFi resilience** | None | Watchdog daemon (30s loop) | None |
| **OTA updates** | None (read-only FS) | Git pull via cron (app only) | None (by design) |
| **Read-only rootfs** | Yes (overlayfs) | No | No |
| **CEC support** | Yes (cec2kbd) | No | Yes (scripts) |
| **First-boot setup** | Enables overlay FS, reboots | WiFi config file | Shows welcome HTML page |
| **Image size** | Minimal (no desktop) | Minimal (no desktop) | Minimal (no desktop) |
| **Reproducible build** | Yes (scripted pi-gen) | Yes (scripted pi-gen) | Partially (requires live Pi) |

---

## WiFi First-Boot Configuration Patterns

None of the three projects implement a captive portal for WiFi. The common patterns found across the ecosystem:

### Pattern 1: Boot Partition File (most common)
Edit `wpa_supplicant.conf` or a custom config file on the FAT32 boot partition before first power-on. Used by all three projects above.
- **Pro:** Simple, works from any OS
- **Con:** Requires physical SD card access, no reconfiguration after deployment

### Pattern 2: Balena wifi-connect
**URL:** https://github.com/balena-os/wifi-connect (Rust, NetworkManager-based)
- Creates AP + captive portal when no known networks are available
- User connects phone to AP, selects network, enters password
- **Pro:** True headless WiFi provisioning
- **Con:** Requires NetworkManager (replaces dhcpcd), incompatible with some WiFi chipsets (BCM43143, MT7601, RTL8188CUS), heavy dependency

### Pattern 3: Comitup
**URL:** https://github.com/davesteele/comitup (356 stars, Python, NetworkManager-based)
- Similar to wifi-connect: AP mode + captive portal + web UI for network selection
- Available as apt package (`sudo apt-get install comitup`) or pre-built image
- Actively maintained (updated 2026-03-18)
- **Pro:** Apt-installable, can be added to pi-gen stage. Supports dual-interface routing.
- **Con:** Requires NetworkManager, Bookworm needs updated python3-networkmanager package

### Pattern 4: Raspberry Pi Imager Pre-configuration
Modern Raspberry Pi OS supports WiFi pre-configuration via Raspberry Pi Imager's customization tab, which writes firstrun.sh to the boot partition.
- **Pro:** Official, zero-code
- **Con:** Only works with the Imager tool, not programmatic

**Recommendation for framecast:** Comitup is the best fit. It's apt-installable (easy to add as a pi-gen stage package), actively maintained, provides a polished captive portal, and handles the fallback-to-AP pattern gracefully. The NetworkManager dependency is a tradeoff but acceptable for a dedicated appliance image.

---

## OTA Update Patterns

### Pattern 1: Application-level git pull (mrworf/photoframe)
- Cron job runs `git pull` on the application repo
- Simple, works for interpreted languages (Python, JS)
- Does NOT update OS packages, kernel, or system config
- Breaks if user modifies application files locally

### Pattern 2: No updates (chilipie-kiosk, kiosk.pi)
- Ship a known-good image, never change it
- Most reliable for unattended operation
- Requires physical SD card access to update

### Pattern 3: rpi-image-gen A/B OTA (official Raspberry Pi)
**URL:** https://github.com/raspberrypi/rpi-image-gen (examples/ota/)
- Uses A/B partition layout (two bootable root partitions)
- OTA via Raspberry Pi Connect
- `trixie-minbase-ab.yaml` base config + `example-ota` layer + `rpi-connect-ota` layer
- **Pro:** Full system OTA with rollback, officially supported
- **Con:** Requires rpi-image-gen (not pi-gen), new tool, Pi 5 focused, experimental

### Pattern 4: SWUpdate / RAUC
- Industry-standard A/B rootfs update frameworks
- Can be integrated into pi-gen images
- Heavy setup, designed for production IoT deployments

### Pattern 5: Git pull + systemd timer (hybrid)
- Pull application code via git, pull OS updates via `apt upgrade` on a timer
- Restart services after update
- Risk: `apt upgrade` can break things on a headless device

**Recommendation for framecast:** Start with application-level git pull (Pattern 1) for the framecast application code, combined with a read-only rootfs overlay (like kiosk.pi). The overlay protects the OS while allowing application updates to a persistent data partition. If full OS OTA is needed later, migrate to rpi-image-gen's A/B layout.

---

## Pi-Gen Stage Customization Best Practices

Synthesized from all projects studied plus the official documentation:

### Stage Structure
```
stage2-framecast/
  prerun.sh                    # Always: copy_previous
  EXPORT_IMAGE                 # Triggers image export
  00-packages/
    00-packages                # apt packages (one per line)
    00-packages-nr             # apt packages without recommends
  01-config/
    01-run.sh                  # Host-context: install files via install -m
    files/
      config.txt               # /boot/config.txt overrides
      cmdline.txt              # /boot/cmdline.txt
  02-app/
    01-run.sh                  # Clone/install application code
    01-run-chroot.sh           # Chroot: systemctl enable, user creation, etc.
    files/
      framecast.service        # systemd unit
```

### Config File
```
IMG_NAME="FrameCast"
RELEASE="bookworm"
TARGET_HOSTNAME="framecast"
FIRST_USER_NAME="pi"
FIRST_USER_PASS="<changeme>"
ENABLE_SSH=1
LOCALE_DEFAULT="en_US.UTF-8"
KEYBOARD_KEYMAP="us"
TIMEZONE_DEFAULT="America/New_York"
STAGE_LIST="stage0 stage1 stage2 stage2-framecast"
```

### Key Gotchas (from pi-gen issues + practitioner blogs)
1. **Build time:** 20-60+ minutes depending on host and stages. Use SKIP files to iterate on individual stages.
2. **DNS resolution failures in chroot:** `apt-get update` can fail inside chroot. The export-image stage has a resolv.conf setup step -- make sure it runs.
3. **Stage ordering matters:** `STAGE_LIST` must be in order. Stages build on previous stage's rootfs via `copy_previous`.
4. **Directory locking on failure:** pi-gen locks the work directory. May need to manually clean `/pi-gen/work/` or restart the build host after a crash.
5. **CONTINUE=1:** Set this to resume from the last successful stage instead of rebuilding everything.
6. **Docker builds:** `build-docker.sh` is more reliable than bare-metal builds for reproducibility.
7. **Bookworm changes:** Some packages changed names. Test package lists against the target release.
8. **Disk space:** Need 10-20GB+ free in the work directory.
9. **QEMU limits:** Git clone inside chroot can hang under QEMU emulation. The mrworf approach of cloning on the host and copying in is safer.
10. **File permissions:** Use `install -m <mode> -o <uid> -g <gid>` for all file installations. Don't rely on umask.

---

## Bonus: rpi-image-gen (Official Raspberry Pi)

**URL:** https://github.com/raspberrypi/rpi-image-gen
**Stars:** ~new | **Focus:** Pi 5, Trixie, modern tooling

A newer alternative to pi-gen from the Raspberry Pi Foundation. Uses `mmdebstrap` + YAML layer definitions instead of pi-gen's stage/shell script approach.

**Key differences from pi-gen:**
- YAML-based configuration (layers with metadata headers)
- Uses `mmdebstrap` for debootstrap (faster, more hermetic)
- Built-in support for A/B partition layouts and OTA via Raspberry Pi Connect
- Layer dependency system (`X-Env-Layer-Requires`)
- Template substitution in service files (`envsubst`)
- Designed for Pi 5 / Trixie; backwards compatibility unclear

**Webkiosk example uses:**
- `cage` Wayland compositor (not X11)
- Chromium in kiosk mode
- systemd service with `Restart=always`

**Worth watching** but pi-gen remains the proven, well-documented choice for Pi 3/4/Zero builds today. rpi-image-gen is the future direction.

---

## Sources

- [RPi-Distro/pi-gen](https://github.com/RPi-Distro/pi-gen) -- 3,139 stars, official image build tool
- [deltazero-cz/kiosk.pi](https://github.com/deltazero-cz/kiosk.pi) -- Pi-gen kiosk image builder
- [mrworf/photoframe](https://github.com/mrworf/photoframe) -- Google Photos photo frame
- [mrworf/pi-gen (photoframe branch)](https://github.com/mrworf/pi-gen/tree/photoframe) -- Pi-gen fork for photoframe
- [jareware/chilipie-kiosk](https://github.com/jareware/chilipie-kiosk) -- 1,397 stars, popular kiosk image
- [raspberrypi/rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen) -- Official next-gen image builder
- [balena-os/wifi-connect](https://github.com/balena-os/wifi-connect) -- Captive portal WiFi provisioning
- [davesteele/comitup](https://github.com/davesteele/comitup) -- 356 stars, WiFi provisioning via AP+captive portal
- [taquitos/PiFrame](https://github.com/taquitos/PiFrame) -- Auto-updating photo frame (git pull + rclone)
- [sepfy/raspberrypi-ota](https://github.com/sepfy/raspberrypi-ota) -- Initramfs-based OTA updates
- [Pi-gen Customization Guide (DeepWiki)](https://deepwiki.com/RPi-Distro/pi-gen/5-customization-guide)
- [Using Pi-Gen to Build a Custom Raspbian Lite Image (Geoff Hudik)](https://geoffhudik.com/tech/2020/05/15/using-pi-gen-to-build-a-custom-raspbian-lite-image/)
- [Making KioskPi (Medium)](https://medium.com/@deltazero/making-kioskpi-custom-raspberry-pi-os-image-using-pi-gen-99aac2cd8cb6)
