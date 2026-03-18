# FrameCast

**Turn any TV into a family photo frame -- no app, no cloud, no subscription.**

FrameCast runs on a Raspberry Pi connected to your TV or monitor over HDMI. Anyone on your WiFi can upload photos and videos from their phone's browser. It starts itself, survives power outages, and even creates its own WiFi hotspot when your internet goes down.

---

## Why FrameCast

- **No app to install.** Open a browser, drag in your photos, done. Works from any phone, tablet, or computer.
- **No cloud dependency.** Your photos stay on the Pi, on your network, in your home. Nothing is uploaded to the internet.
- **No babysitting.** It boots, it plays, it recovers. The reliability stack scores a 9.9 out of 10 -- crash recovery, hardware watchdog, memory management, and self-healing config mean it just keeps running.
- **No network? No problem.** If WiFi drops, FrameCast creates its own hotspot so you can still upload photos directly.
- **See where your photos were taken.** A built-in world map plots every geotagged photo, right in the browser -- no internet connection needed.

---

## Features

### Display

- Full-screen slideshow on any HDMI TV or monitor using VLC
- Photos and videos in the same slideshow (JPG, PNG, GIF, WEBP, TIFF, MP4, MKV, AVI, MOV, and more)
- Shuffle or sequential playback with adjustable photo duration
- Welcome screen with a QR code when no photos have been added yet
- HDMI schedule to turn the screen off at night and back on in the morning

### Upload and Management

- Web interface at **http://photoframe.local:8080** -- upload, preview, and delete from any browser
- Drag-and-drop upload with progress indication
- Gallery view with lightbox preview for photos and thumbnail previews for videos
- Auto-resize of oversized images (large phone photos are downscaled to screen resolution)
- Disk space indicator so you always know how much room is left
- Delete individual files or clear everything at once with confirmation
- Duplicate filename handling (no files are silently overwritten)

### Photo Map

- Interactive world map at **http://photoframe.local:8080/map**
- GPS coordinates are automatically extracted from photo EXIF data on upload
- Hover or tap a dot to see the filename and exact coordinates
- Works entirely offline -- the map is a self-contained SVG, no tile server or internet required
- The Map link appears in navigation only when geotagged photos exist

### Reliability

- Automatic start on boot -- plug in the power and walk away
- Crash recovery with exponential backoff (up to 5 rapid failures before quarantine)
- Hardware watchdog reboots the Pi if the entire system freezes
- Proactive VLC restart every 6 hours to prevent memory leaks
- Memory watchdog restarts VLC before the out-of-memory killer can strike
- Corrupt media files are automatically quarantined and removed from rotation
- Atomic file writes for uploads and configuration (survives power loss mid-write)
- Filesystem health check on boot detects and remounts read-only SD cards
- Self-healing configuration restores from template if `.env` is missing or corrupt
- Hourly self-test checks VLC health, disk space, config integrity, and media directory
- SD card longevity optimizations: tmpfs for /tmp, noatime mount, journal size caps

### Network

- Reachable at **http://photoframe.local:8080** via mDNS (Avahi)
- WiFi AP fallback creates a "PiPhotoFrame" hotspot when no WiFi is available
- Automatic reconnection to your home network when it comes back
- Reboot and shutdown controls accessible from the browser
- Optional PIN protection for all destructive operations (upload, delete, settings, reboot)

---

## What You Need

| Item | Notes |
|------|-------|
| Raspberry Pi 3B or newer | Pi 3B, 3B+, 4, and 5 are all supported |
| microSD card, 16 GB minimum | 32 GB recommended if you plan to store many photos |
| Power supply for your Pi model | USB-C for Pi 4/5, micro-USB for Pi 3 |
| HDMI cable | Micro-HDMI adapter required for Pi 4 and 5 |
| Any TV or monitor with HDMI | A small 7-inch or 10-inch HDMI display works well as a dedicated frame |

---

## Quick Start

### Step 1: Flash the SD Card

Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and install **Raspberry Pi OS with Desktop** (32-bit or 64-bit) to your microSD card.

Before writing, click the gear icon (or "Edit Settings") and set:
- **Hostname:** `photoframe`
- **Enable SSH:** Yes
- **Username and password:** Choose something you will remember
- **WiFi:** Enter your home network name and password

Insert the card into your Pi and power it on.

### Step 2: Install FrameCast

Wait about two minutes for the Pi to boot. From another computer on the same network, open a terminal and run:

```bash
ssh your-username@photoframe.local
```

Then install:

```bash
git clone https://github.com/bobburgers7/pi-video-photo-slideshow.git
cd pi-video-photo-slideshow
sudo bash install.sh
```

The installer takes a few minutes and reboots the Pi automatically when finished.

### Step 3: Add Your Photos

Open **http://photoframe.local:8080** on your phone or computer. Drag and drop your photos, or tap Browse Files to select them. They appear on the TV within about 30 seconds.

---

## First Boot Experience

Here is what happens the first time the Pi starts after installation:

1. The Pi boots to the desktop automatically (no login screen).
2. Since there are no photos yet, the TV shows a **welcome screen** with a **QR code** and the web address for uploading.
3. Scan the QR code with your phone's camera, or type the address into your browser.
4. Upload your first photos. The slideshow starts automatically within 30 seconds.

If the Pi cannot connect to your WiFi (for example, you brought it to a new location), it creates its own hotspot after 30 seconds:

| Detail | Value |
|--------|-------|
| WiFi network name | **PiPhotoFrame** |
| WiFi password | **photoframe** |
| Upload page | **http://192.168.4.1:8080** |

Connect your phone to the PiPhotoFrame network and open `http://192.168.4.1:8080` to get started.

---

## Photo Map

When you upload photos taken with a phone camera, FrameCast reads the GPS coordinates embedded in each photo's EXIF data. These locations are plotted on an interactive world map available at:

**http://photoframe.local:8080/map**

The map is entirely self-contained -- it uses an SVG projection with simplified continent outlines, not internet map tiles. This means it works even when the Pi has no internet connection. Hover over any dot to see the photo's filename and coordinates. On a phone, tap a dot once to see the tooltip, and double-tap to open the photo.

The map link only appears in the navigation bar when at least one photo has GPS data. Photos without location data are silently skipped (they still display in the slideshow as normal).

---

## Settings

Open **http://photoframe.local:8080/settings** to configure FrameCast from your browser. No command line needed.

Available options:

- **Photo Duration** -- seconds each photo stays on screen
- **Shuffle** -- random or sequential playback order
- **Loop** -- repeat forever or stop after one pass
- **HDMI Schedule** -- turn the display off at night and on in the morning
- **HDMI Off / On Times** -- set the exact times (24-hour format)
- **Max Upload Size** -- per-file upload limit
- **Auto-Resize Max** -- largest dimension for automatic image downscaling (set to 0 to disable)
- **Auto-Refresh** -- restart the slideshow automatically when files change
- **Refresh Interval** -- how often to check for new files
- **Image / Video Extensions** -- customize which file types are accepted

The settings page also provides **Device Power** buttons to reboot or shut down the Pi from your browser.

After changing settings, check "Apply immediately" and click **Save Settings** to restart the slideshow with your new configuration.

### Configuration Reference

All settings are stored in `/opt/pi-photo-display/app/.env`. You can edit this file directly over SSH if you prefer.

| Variable | Default | Description |
|----------|---------|-------------|
| `MEDIA_DIR` | `/home/<user>/media` | Where photos and videos are stored |
| `PHOTO_DURATION` | `10` | Seconds each photo is displayed |
| `SHUFFLE` | `yes` | Randomize playback order |
| `LOOP` | `yes` | Repeat the slideshow continuously |
| `WEB_PORT` | `8080` | Port for the web interface |
| `MAX_UPLOAD_MB` | `200` | Maximum file size for uploads (MB) |
| `AUTO_RESIZE_MAX` | `1920` | Max pixel dimension for auto-resize (0 = disabled) |
| `WEB_PASSWORD` | *(empty)* | PIN to protect uploads, deletes, and settings |
| `FLASK_SECRET_KEY` | *(auto-generated)* | Internal security key (do not share) |
| `IMAGE_EXTENSIONS` | `.jpg,.jpeg,.png,.bmp,.gif,.webp,.tiff` | Accepted photo formats |
| `VIDEO_EXTENSIONS` | `.mp4,.mkv,.avi,.mov,.webm,.m4v,.mpg,.mpeg` | Accepted video formats |
| `HDMI_SCHEDULE_ENABLED` | `no` | Enable timed display on/off |
| `HDMI_OFF_TIME` | `22:00` | Time to turn the display off |
| `HDMI_ON_TIME` | `08:00` | Time to turn the display on |
| `AUTO_REFRESH` | `yes` | Restart slideshow when files change |
| `REFRESH_INTERVAL` | `30` | Seconds between file change checks |

If you edit `.env` directly, restart the services for changes to take effect:

```bash
sudo systemctl restart slideshow
sudo systemctl restart photo-upload
```

---

## WiFi Hotspot Mode

If the Pi cannot reach your WiFi network -- maybe the router is off, or you moved the frame to a new house -- it automatically creates its own WiFi hotspot within 30 seconds.

- **Network name:** PiPhotoFrame
- **Password:** photoframe
- **Web upload at:** http://192.168.4.1:8080

While in hotspot mode, the Pi checks every 60 seconds for your regular WiFi network. When it comes back, FrameCast reconnects automatically and the hotspot turns off.

This means the photo frame always works, even without a router. You can always connect to it and add photos.

The hotspot works on both newer Pi OS versions (Bookworm and later, using NetworkManager) and older ones (Bullseye, using hostapd and dnsmasq). FrameCast detects which backend is available and uses the right one.

---

## Security

FrameCast is designed for trusted home networks. By default, anyone on your WiFi can upload and delete photos.

To add a layer of protection, set a PIN in the `.env` file:

```
WEB_PASSWORD=1234
```

When a PIN is set, any action that modifies data (uploading, deleting, changing settings, rebooting) prompts for a password in the browser. You can use any username; only the password must match the PIN.

Other security measures in place:

- `.env` file permissions are set to 600 (readable only by the Pi user)
- Systemd services run sandboxed with `ProtectSystem`, `NoNewPrivileges`, `PrivateTmp`, and memory limits
- Path traversal is blocked on file deletion
- The media directory is validated against a safe-path allowlist
- Dangerous file extensions (`.exe`, `.sh`, `.py`, `.html`, `.js`, etc.) are rejected
- Security headers are set on all responses (X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy)
- Uploads use atomic write-then-rename to prevent serving partial files

---

## Reliability: The 9.9/10 Stack

FrameCast is built to run unattended for months. Here is how each failure mode is handled:

| What Goes Wrong | What FrameCast Does |
|-----------------|---------------------|
| VLC crashes | Restarts automatically within 10 seconds, with backoff if crashing repeatedly |
| A corrupt photo crashes VLC repeatedly | Quarantines the suspect file and continues with the rest |
| VLC slowly leaks memory | Proactively restarts VLC every 6 hours, before it becomes a problem |
| Available RAM drops dangerously low | Restarts VLC to free memory before the kernel's OOM killer intervenes |
| The entire Pi freezes | Hardware watchdog reboots the Pi within 15 seconds |
| Power goes out | Pi boots and starts the slideshow automatically when power returns |
| `.env` config file gets corrupted | Auto-restores from the template and regenerates the secret key |
| SD card goes read-only after unclean shutdown | Detects and remounts the filesystem read-write on boot |
| Upload interrupted by power loss | Temp files are cleaned up on next start; no corrupt files are served |
| Disk fills up | Uploads are rejected with a clear message; 50 MB is reserved for system use |

Additionally, an hourly self-test verifies VLC is responding, disk space is adequate, `.env` is readable, and the media directory is writable. Results are logged to the system journal.

---

## Troubleshooting

### The slideshow is not starting

- **Is Pi OS Desktop installed?** FrameCast needs the Desktop version, not the Lite version. VLC requires a graphical display server.
- **Are there any photos?** Check that files exist: `ls ~/media/`
- **Check the service log:** `journalctl -u slideshow -f`

### I cannot reach the web interface

- Make sure your device is on the same WiFi network as the Pi.
- Try the IP address directly instead of `photoframe.local`:
  ```bash
  hostname -I    # run this on the Pi to find its IP
  ```
  Then open `http://<that-ip>:8080` in your browser.
- Verify the web service is running: `sudo systemctl status photo-upload`

### Videos stutter or do not play

- The Pi 3B handles 1080p H.264 video well. 4K or H.265/HEVC content may stutter.
- On Pi 3 and older, ensure GPU memory is set to 128 MB (check `/boot/config.txt` for `gpu_mem=128`).
- Convert problem videos to 1080p H.264 MP4 on your computer before uploading.

### The screen is black

- The HDMI schedule may have turned the screen off. Turn it back on:
  ```bash
  /opt/pi-photo-display/app/hdmi-control.sh on
  ```
- Check if screen blanking is active: `xset q`

### WiFi hotspot is not appearing

- The hotspot only activates when the Pi cannot connect to any known WiFi network.
- Wait at least 30 seconds after boot for the fallback to engage.
- Check the wifi-manager service:
  ```bash
  journalctl -u wifi-manager -f
  ```

### Uploads fail or time out

- Check available disk space (shown on the web interface home page).
- The default upload limit is 200 MB per file. Increase it in Settings if needed.
- Large uploads over WiFi can be slow. Try uploading fewer files at a time.
- Only two uploads can run simultaneously (to protect the Pi's limited RAM).

### The Pi keeps rebooting on its own

- This is likely the hardware watchdog doing its job after a system hang. Review what happened before the last reboot:
  ```bash
  journalctl -b -1
  ```
- To shut down intentionally, use the Shut Down button in Settings, or:
  ```bash
  sudo shutdown -h now
  ```

---

## Project Structure

```
pi-video-photo-slideshow/
|-- install.sh                       # One-step installer (run with sudo)
|-- Makefile                         # Convenience targets: install, update, status, logs, test
|-- requirements.txt                 # Python dependencies
|-- VERSION                          # Current version (1.0.0)
|-- CHANGELOG.md                     # Release notes
|-- CONTRIBUTING.md                  # Contribution guidelines
|-- scripts/
|   |-- smoke-test.sh                # Post-install validation (30 checks)
|-- app/
|   |-- .env.example                 # Configuration template
|   |-- web_upload.py                # Flask web server (upload, gallery, settings, API)
|   |-- slideshow.sh                 # VLC slideshow controller with crash recovery
|   |-- hdmi-control.sh              # Display on/off/status control
|   |-- wifi-manager.sh              # WiFi AP fallback manager
|   |-- wifi-setup-install.sh        # Hotspot service installer
|   |-- generate-welcome.sh          # Welcome screen generator (created by installer)
|   |-- modules/
|   |   |-- config.py                # .env read/write with atomic saves
|   |   |-- media.py                 # File listing, GPS extraction, disk usage
|   |   |-- services.py              # Systemd service status and control
|   |-- templates/
|   |   |-- index.html               # Gallery and upload page
|   |   |-- settings.html            # Settings page
|   |   |-- map.html                 # Photo locations map
|   |-- static/
|       |-- welcome.png              # Generated welcome screen with QR code
```

---

## Architecture

```
+-----------------------------------------------+
|                 Raspberry Pi                   |
|                                                |
|  +--------------+       +-----------------+    |
|  | slideshow.sh |       |  web_upload.py  |    |
|  |    (VLC)     |       |    (Flask)      |    |       +------------+
|  |              |       |                 |    | WiFi  |  Phone /   |
|  | Reads media, |       | Upload, delete, |<---------->|  Computer  |
|  | plays on TV  |       | settings, API,  |    |       |  Browser   |
|  +------+-------+       | map, gallery    |    |       +------------+
|         |               +--------+--------+    |
|         |                        |             |
|         +----------+-------------+             |
|                    |                           |
|            +-------v--------+                  |
|            |   ~/media/      |                  |
|            | photos & videos |                  |
|            +----------------+                  |
|                                                |
|  +-----------------+    +-----------------+    |
|  | hdmi-control.sh |    | wifi-manager.sh |    |
|  | Screen on/off   |    | AP fallback     |    |
|  | via schedule     |    | when no WiFi    |    |
|  +-----------------+    +-----------------+    |
|                                                |
|  +------------------------------------------+ |
|  |            systemd services               | |
|  | Auto-start, auto-restart, watchdog,       | |
|  | sandboxing, memory limits                 | |
|  +------------------------------------------+ |
+-----------------------------------------------+
                      |
                      | HDMI
                      v
              +---------------+
              |  TV / Monitor |
              +---------------+
```

---

## For Developers

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Gallery and upload page (HTML) |
| `POST` | `/upload` | Upload files (multipart form data) |
| `POST` | `/delete` | Delete a single file (`filename` form field) |
| `POST` | `/delete-all` | Delete all files (requires `confirm=DELETE`) |
| `GET` | `/media/<filename>` | Serve a media file directly |
| `GET` | `/thumbnail/<filename>` | Serve a video thumbnail |
| `GET` | `/map` | Photo locations map (HTML) |
| `GET` | `/settings` | Settings page (HTML) |
| `POST` | `/settings` | Save settings (form data) |
| `GET` | `/api/status` | JSON: photo count, video count, disk usage, slideshow state |
| `GET` | `/api/locations` | JSON: GPS coordinates for all geotagged photos |
| `POST` | `/api/restart-slideshow` | Restart the slideshow service |
| `POST` | `/api/reboot` | Reboot the Pi |
| `POST` | `/api/shutdown` | Shut down the Pi |

All `POST` endpoints require HTTP Basic Auth when `WEB_PASSWORD` is set. Use any username; the password must match the configured PIN.

### Service Commands

```bash
# Check status of all services
sudo systemctl status slideshow photo-upload wifi-manager

# View live logs
journalctl -u slideshow -f
journalctl -u photo-upload -f
journalctl -u wifi-manager -f

# Restart a service
sudo systemctl restart slideshow
sudo systemctl restart photo-upload

# Stop a service
sudo systemctl stop slideshow

# Disable a service from starting on boot
sudo systemctl disable wifi-manager
```

### Makefile Targets

Run these from the project directory on the Pi:

| Target | Command | What It Does |
|--------|---------|--------------|
| Install | `sudo make install` | Run the full installer |
| Uninstall | `sudo make uninstall` | Remove services and install directory (preserves your photos) |
| Update | `sudo make update` | Pull latest changes and re-install (preserves config) |
| Status | `make status` | Show service status, web server health, disk usage |
| Logs | `make logs` | Show recent logs from all three services |
| Test | `make test` | Run the smoke test suite |

### Smoke Test

After installation, run the smoke test to verify everything is working:

```bash
bash scripts/smoke-test.sh
```

The test checks 30 items: install directory, config file, media directory, all three systemd services, web server responsiveness, API endpoints, VLC process, hardware watchdog, system dependencies (VLC, Python, ffmpeg, qrencode), Pillow availability, mDNS/Avahi, and sudoers permissions.

### Updating

To update to the latest version:

```bash
cd pi-video-photo-slideshow
git pull
sudo bash install.sh
```

Your settings in `.env` are automatically preserved across re-installs. The installer backs up your configuration, copies new files, and restores your settings.

### Contributing

1. Fork this repository.
2. Create a branch for your changes.
3. Test on a real Raspberry Pi if possible.
4. Submit a pull request with a clear description of what you changed and why.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## Credits

Based on [pi-video-photo-slideshow](https://github.com/bobburgers7/pi-video-photo-slideshow) by bobburgers7.

## License

MIT License -- see [LICENSE](LICENSE) for details.
