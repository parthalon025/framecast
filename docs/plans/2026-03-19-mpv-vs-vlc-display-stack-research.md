# mpv vs VLC Display Stack Research for Raspberry Pi Photo Frame

**Date:** 2026-03-19
**Purpose:** Detailed comparison of mpv, VLC, and framebuffer tools for FrameCast's photo/video display on Raspberry Pi 3/4/5 (arm64, Bookworm). Evaluate DRM/KMS feasibility, boot-time impact, and whether X11 can be eliminated.

---

## BLUF / Recommendation

**Stay with VLC for video playback. Use mpv with `--vo=drm` for photo slideshow and static image display (QR codes, welcome screens). Use Plymouth for boot splash. Do not use X11.**

Rationale:
- VLC has superior hardware decode support on Pi (patched by RPi Foundation), especially for HEVC
- mpv `--vo=drm` works for images without X11 and is lighter than VLC for static display
- fbi/fim are unreliable on Bookworm KMS — not recommended
- Plymouth handles early-boot display (QR code) cleanly without any runtime display tool
- X11 adds 5-15s boot time and ~60-100MB RAM overhead for no benefit in a headless photo frame

---

## 1. Hardware Video Decode

### H.264

| Feature | Pi 3 | Pi 4 | Pi 5 |
|---------|-------|------|------|
| H.264 HW decode | Yes (v4l2m2m) | Yes (v4l2m2m) | **No** (no H.264 block) |
| Stateful API | Yes | Yes | N/A |
| VLC support | Good | Good | Software only |
| mpv support | Works via `--hwdec=v4l2m2m-copy` | Works via `--hwdec=v4l2m2m-copy` | Software only |

### HEVC (H.265)

| Feature | Pi 3 | Pi 4 | Pi 5 |
|---------|-------|------|------|
| HEVC HW decode | No | Yes (stateless V4L2) | Yes (stateless V4L2, 4K capable) |
| `hevc_v4l2m2m` | N/A | **Does NOT work** (stateless, not stateful) | **Does NOT work** |
| VLC support | N/A | **Works** (uses stateless API directly) | **Works** |
| mpv support | N/A | **Limited** — needs RPi's FFmpeg fork, not in mainline yet | **Limited** — same issue |

**Key finding:** HEVC on Pi uses the V4L2 *stateless* API. FFmpeg's `v4l2m2m` wrapper only handles the *stateful* API. RPi's FFmpeg fork has stateless support, but it hasn't hit mainline as of March 2026. VLC has this patched in. mpv depends on FFmpeg, so it lags behind.

### Winner: VLC

VLC is patched specifically for Pi hardware by the RPi Foundation. For video playback, VLC has significantly better hardware decode coverage, particularly HEVC. mpv requires the `-copy` suffix (CPU memcpy from GPU), adding ~20% more CPU load.

---

## 2. DRM/KMS Output (No X11)

### mpv `--vo=drm`

mpv has a native DRM/KMS video output driver that renders directly to the display without X11 or Wayland.

**Configuration:**
```bash
# Basic image display
mpv --vo=drm --drm-connector=0.HDMI-A-1 --image-display-duration=inf photo.jpg

# Photo slideshow (4 seconds per image)
mpv --vo=drm --drm-connector=0.HDMI-A-1 --image-display-duration=4 /path/to/photos/*

# Using mf:// protocol for explicit frame rate control
mpv --vo=drm --drm-connector=0.HDMI-A-1 mf:///path/to/photos/*.jpg --mf-fps=0.25

# Video playback with hardware decode
mpv --vo=drm --drm-connector=0.HDMI-A-1 --hwdec=drm-copy video.mp4
```

**Key options:**
| Option | Values | Default | Purpose |
|--------|--------|---------|---------|
| `--vo=drm` | — | — | Use DRM/KMS output (no X11) |
| `--drm-connector` | `auto`, `0.HDMI-A-1`, etc. | auto | Select display output |
| `--drm-mode` | `preferred`, `highest`, `WxH[@R]` | preferred | Resolution/refresh |
| `--drm-format` | `xrgb8888`, `xrgb2101010` | xrgb8888 | Pixel format |
| `--drm-draw-plane` | `primary`, `overlay`, N | primary | DRM plane selection |
| `--drm-draw-surface-size` | `WxH` | display res | Render surface size (downscale for perf) |
| `--drm-vrr-enabled` | `no`, `yes`, `auto` | no | Variable refresh rate |
| `--image-display-duration` | seconds or `inf` | `inf` | Time per image in slideshow |

**Stability assessment:**
- Pi 4 (1080p): **Stable.** Multiple reports of `--vo=drm` working for images and video. Use `--hwdec=drm-copy` for HW decode.
- Pi 5 (1080p): **Stable.** Works but drops frames at 4K output resolution even with 1080p content (GitHub issue #17447, still open).
- Pi 5 (4K): **Unstable.** Frame drops, A/V desync. GPU bandwidth issue with vc4/V3D at 4K.
- Pi 3: **Limited testing.** Should work for images. Video performance will be weak (CPU-bound).

**Critical limitation:** `--vo=drm` does NOT support hardware acceleration directly. For HW accel, use `--vo=gpu --gpu-context=drm --gpu-api=opengl`. However, this has more compatibility issues on Pi (frame drops at 4K, Mesa/V3D driver bugs).

### VLC DRM/KMS

VLC does not have a clean DRM/KMS output mode equivalent to mpv's `--vo=drm`. VLC on Pi typically requires:
- X11 or Wayland for GUI rendering, OR
- `cvlc` with `--vout=mmal_vout` (Pi-specific, legacy, removed from Bookworm KMS stack)

On Bookworm with mandatory KMS, VLC's headless options are more limited.

### Winner: mpv (for DRM/KMS output)

mpv has a purpose-built DRM output driver. VLC does not.

---

## 3. Photo Slideshow Capability

### mpv

mpv can display images and create slideshows natively:

```bash
# Slideshow: 5 seconds per image, loop forever
mpv --vo=drm --image-display-duration=5 --loop-playlist=inf /photos/*.jpg

# Alternative using mf:// (more control)
mpv --vo=drm mf:///photos/*.jpg --mf-fps=0.2 --loop=inf

# With shuffle
mpv --vo=drm --image-display-duration=5 --loop-playlist=inf --shuffle /photos/*
```

**Supported formats:** JPG, PNG, BMP, GIF, TIFF, WebP (via FFmpeg decoders — anything FFmpeg can decode, mpv can display).

**Transitions:** mpv has **no built-in transition effects** (no fade, crossfade, slide, etc.). Images switch instantly. Transitions would require:
- Pre-processing with FFmpeg (encode slideshow as video with transitions)
- A custom Lua script (mpv supports Lua scripting, but DRM output limits shader capabilities)
- External compositing

**Playlist management:** mpv supports `--playlist=file.txt` with one path per line, `--shuffle`, `--loop-playlist`, and IPC control via `--input-ipc-server=/tmp/mpvsocket` for runtime commands (add/remove files, skip, pause).

### VLC

```bash
cvlc --image-duration=5 --loop /photos/*.jpg
```

VLC's image demuxer works but has a documented issue: **100% CPU on one core when displaying images** on Pi (RPi-Distro/vlc issue #29). The image demuxer is not optimized for the Pi platform.

### Winner: mpv (for photos)

Lower CPU for static images, native DRM output, IPC control. VLC's image demuxer is CPU-heavy on Pi.

---

## 4. Memory Usage

Exact RSS measurements are scarce in public benchmarks. Estimated from forum reports and general characteristics:

| Metric | mpv (DRM, photo) | mpv (DRM, video) | VLC (video) | VLC (photo) |
|--------|-------------------|-------------------|-------------|-------------|
| Base RSS | ~30-50 MB | ~50-80 MB | ~80-120 MB | ~80-120 MB |
| GPU mem | Minimal | 76 MB default | 76 MB default | 76 MB default |
| CPU idle (photo) | ~1-5% | — | — | ~25-100% one core |
| CPU (1080p video) | ~35%/core (`-copy`) | ~35%/core | ~15%/core (HW) | — |

**Key findings:**
- mpv is lighter than VLC for photo display (no GUI toolkit, no plugin system overhead)
- VLC has a reported **memory leak** in headless cvlc mode on Pi Zero 2W — cache creeps up ~240KB/min, eventually OOM
- For video playback, VLC uses less CPU because its HW decode path avoids the `-copy` penalty
- GPU memory default of 76MB is sufficient for both; increasing it wastes RAM

### Winner: mpv for photos, VLC for video

---

## 5. Framebuffer Alternatives (fbi / fim)

### fbi (Linux Framebuffer Imageviewer)

```bash
sudo fbi -T 1 -d /dev/fb0 -a -noverbose -t 5 /photos/*.jpg
```

**Options:** `-T 1` (virtual terminal), `-a` (auto-zoom), `-t 5` (5 sec per image), `-noverbose` (no filename overlay)

**Bookworm KMS compatibility: PROBLEMATIC.**
- Bookworm uses mandatory KMS (`vc4-kms-v3d`). Legacy `fkms` driver is removed.
- `/dev/fb0` exists as a KMS framebuffer emulation layer, but:
  - Any DRM client (mpv, VLC, Wayland compositor) **evicts the emulated framebuffer**
  - Framebuffer settings in `config.txt` are mostly ignored (only firmware uses them during boot)
  - Resolution must be set via `video=` in `cmdline.txt` instead
- Multiple forum reports of fbi failing or producing garbled output on Bookworm
- fbi requires `sudo` or video group membership for DRM master access

**fim:** Updated fork of fbi with more features. Same framebuffer limitations apply.

### Assessment: NOT RECOMMENDED on Bookworm

fbi/fim depend on the legacy framebuffer interface. On Bookworm's mandatory KMS, they are unreliable. The emulated `/dev/fb0` is fragile and conflicts with DRM clients. Use mpv `--vo=drm` instead — it speaks KMS natively.

---

## 6. Boot Time Impact

### Measurements (Bookworm, from community benchmarks)

| Configuration | Pi 4 | Pi 5 | Notes |
|---------------|------|------|-------|
| Lite (console, no desktop) | ~15-20s | ~10-14s | Minimal services |
| Lite + optimized | ~8-12s | ~5-8s | Disabled swap, BT, avahi, etc. |
| Desktop (Wayland) | ~25-35s | ~18-25s | Full desktop environment |
| Desktop (X11/Openbox) | ~25-35s | ~18-25s | Similar to Wayland |

**X11 overhead:** Adding X11 to a Lite image (install xorg + openbox + lightdm) adds:
- ~5-15 seconds to boot time (LightDM startup, X server init)
- ~60-100 MB additional RAM (X server + window manager + display manager)
- Ongoing CPU overhead from X event loop

**DRM-only approach:**
- No display server boot time
- First image can appear within 1-2 seconds of userspace init via a systemd service
- Plymouth can show a splash image during kernel boot (before userspace)

### Optimization targets for FrameCast (Lite + DRM):

Services to disable:
- `triggerhappy.service`, `dphys-swapfile.service`, `keyboard-setup.service`
- `alsa-restore.service`, `avahi-daemon.service`, `bluetooth.service`
- `hciuart.service`, `ModemManager.service`
- `lightdm.service` (if installed), `plymouth-*` (after boot splash shown)

Target: **8-12s to first image on Pi 4, 5-8s on Pi 5**

### Winner: No-X11 DRM approach (saves 5-15s + 60-100MB RAM)

---

## 7. Known Pi-Specific Issues with mpv

### Showstoppers

| Issue | Severity | Pi Model | Status |
|-------|----------|----------|--------|
| 4K output drops frames with `--vo=gpu --gpu-context=drm` | High | Pi 5 | Open (GH #17447) |
| HEVC HW decode requires RPi FFmpeg fork (not in mainline) | Medium | Pi 4/5 | Pending kernel upstreaming (est. 2025-2026) |
| `v4l2m2m` DRM format mismatch (yuv420p unsupported) | Medium | Pi 4 | Use `-copy` suffix workaround |

### Non-showstoppers for photo frame use

| Issue | Impact | Workaround |
|-------|--------|------------|
| No transition effects in mpv | UX only | Pre-render transitions with FFmpeg, or accept hard cuts |
| `--vo=drm` has no OSD/subtitles overlay | Minor | Not needed for photo frame |
| Composite video output reports "disconnected" | None | HDMI only for FrameCast |
| Mesa/V3D bugs on Pi 5 for framebuffer drawing (SDL#8579) | None | Affects SDL apps, not mpv DRM |
| mpv repo package lacks HW accel | Medium | Compile from source or use RPi's mpv package |

### Pi 3 specific

- Pi 3's VideoCore IV is significantly weaker than Pi 4/5's VideoCore VI/VII
- H.264 HW decode works via `v4l2m2m` but HEVC is not available (no HEVC block)
- `--vo=drm` for images should work fine (no GPU-intensive rendering needed)
- Video playback will be CPU-bound for anything above 720p without HW decode

---

## 8. Can X11 Be Started Temporarily?

**Yes, but it's messy and not recommended.**

```bash
# Start X on tty1 with a simple program
startx /usr/bin/feh --fullscreen qrcode.png -- :0 vt1

# Kill it later
pkill -x Xorg
```

**Problems:**
1. Display state after killing X is unpredictable — may leave screen blank, garbled, or on the wrong VT
2. Requires `ioctl(KDSETMODE, KD_TEXT)` to restore console text mode
3. The KMS state may need a mode-set to recover (display stays in X's last resolution/format)
4. DRM master handoff is not guaranteed to be clean — mpv `--vo=drm` may fail to acquire DRM master after X exits
5. Boot time penalty if X packages are installed (even if not auto-started)
6. Package overhead: xorg + deps = ~200-300 MB disk

**Verdict: Do not use X11 at all.** mpv `--vo=drm` handles QR code display directly. Plymouth handles boot-time display. No X11 needed.

---

## 9. mpv and fbi: Display Coexistence

**They cannot coexist on the same DRM output simultaneously.**

DRM is exclusive-access by design. Only one DRM master can control a given CRTC/connector at a time. If mpv holds DRM master, fbi cannot write to `/dev/fb0` (the emulated framebuffer is evicted). If fbi somehow acquires the framebuffer, mpv's DRM init will fail.

**Sequential use is possible** but fragile:
1. fbi displays image → fbi exits → mpv starts with DRM
2. Timing and cleanup must be precise
3. Display may flash/blank during handoff

**Recommendation:** Use mpv for everything. It can display both static images and video via DRM. No need for fbi at all.

---

## 10. Plymouth for Boot Splash / QR Code

Plymouth is the standard Linux boot splash system. It runs in kernel space during early boot, before any userspace display tool.

### Setup on Bookworm

```bash
# Replace splash image
sudo cp qrcode.png /usr/share/plymouth/themes/pix/splash.png

# Rebuild initrd (required on Bookworm — splash is embedded in initrd)
sudo plymouth-set-default-theme --rebuild-initrd pix

# Clean boot display (in /boot/firmware/cmdline.txt)
# Replace console=tty1 with console=tty3 (hides boot messages)
# Add: quiet splash plymouth.ignore-serial-consoles
```

### Capabilities
- Displays a static PNG image during kernel boot
- Runs before any userspace (before systemd, before mpv)
- Can display a QR code as the splash image — just generate the PNG at the right resolution
- Disappears automatically when the display manager or getty starts

### Limitations
- **Static only** — no animation in the `pix` theme (other themes support animation but are heavier)
- **Bookworm quirk** — some users report splash works on shutdown but not boot; may need `initramfs` rebuild
- Cannot be dynamically updated at runtime (it's baked into initrd)
- For a QR code that changes (e.g., includes dynamic WiFi password), you'd need to rebuild initrd each time

### Recommendation for FrameCast

**Use Plymouth for the initial boot splash** (FrameCast logo or static QR code). Then hand off to mpv for dynamic display. The transition is:

1. Power on → Plymouth shows splash.png (QR code or logo) — appears in ~2-3s
2. Kernel boot completes → Plymouth exits
3. systemd starts FrameCast service → mpv `--vo=drm` takes DRM master
4. mpv displays the current QR code / welcome screen / slideshow

For a **dynamic QR code** (WiFi password changes, different network), generate the QR PNG in the FrameCast service startup script and display it via mpv, not Plymouth. Plymouth is only for the static early-boot phase.

---

## Proposed Display Architecture for FrameCast

```
Boot timeline:
├── 0-3s:  Plymouth splash (static logo/QR) — baked in initrd
├── 3-10s: Kernel + systemd boot — screen shows Plymouth or blank
├── 10s+:  FrameCast service starts
│          ├── Generate QR code PNG (if needed)
│          ├── mpv --vo=drm displays QR/welcome screen
│          └── Transition to slideshow/video playback
└── Runtime:
    ├── Photos: mpv --vo=drm --image-display-duration=N --loop-playlist=inf
    ├── Videos: VLC cvlc (for HEVC HW decode on Pi 4/5)
    │   OR:    mpv --vo=drm --hwdec=drm-copy (if HEVC not needed)
    └── Static: mpv --vo=drm --image-display-duration=inf (QR, welcome, error screens)
```

### Decision matrix: When to use which tool

| Content | Tool | Reason |
|---------|------|--------|
| Boot splash | Plymouth | Earliest possible display, no userspace needed |
| QR code / static image | mpv `--vo=drm` | Lightweight, no X11, DRM-native |
| Photo slideshow | mpv `--vo=drm` | Lower CPU than VLC for images, IPC control |
| H.264 video (Pi 3/4) | mpv `--vo=drm --hwdec=v4l2m2m-copy` | HW decode available |
| HEVC video (Pi 4/5) | VLC `cvlc` | Only player with working stateless HEVC on stock Bookworm |
| Any video (Pi 5, H.264) | mpv or VLC (software decode) | Pi 5 has no H.264 block |

### Simplification option

If FrameCast targets Pi 4+ and video content is primarily H.264 (not HEVC), **mpv alone can handle everything** via DRM without X11. This eliminates VLC entirely and reduces complexity. The tradeoff is losing HEVC HW decode on Pi 4/5.

If HEVC support matters, keep VLC as the video backend and mpv as the image/static backend. They can share the DRM output sequentially (one stops, the other starts).

---

## Sources

- [mpv DRM not working - RPi Forums](https://forums.raspberrypi.com/viewtopic.php?t=354884)
- [Accelerated video on RPi (STICKY)](https://forums.raspberrypi.com/viewtopic.php?t=317511)
- [Pi 5 DRM frame drops - mpv GH #17447](https://github.com/mpv-player/mpv/issues/17447)
- [mpv-image-viewer](https://github.com/occivink/mpv-image-viewer)
- [RPi 4 mpv HW decode](https://forums.raspberrypi.com/viewtopic.php?t=345598)
- [RPi 5 mpv not as fast as VLC](https://forums.raspberrypi.com/viewtopic.php?t=360902)
- [Framebuffer and DRM/KMS - RPi Forums](https://forums.raspberrypi.com/viewtopic.php?t=359727)
- [fbi cannot run in framebuffer mode on Bookworm](https://forums.raspberrypi.com/viewtopic.php?t=376060)
- [Pi 5 KMSDRM garbage - SDL GH #8579](https://github.com/libsdl-org/SDL/issues/8579)
- [HEVC decode on Pi 5 solved](https://forums.raspberrypi.com/viewtopic.php?t=381601)
- [How to make mpv use HW accel on Pi 5](https://forums.raspberrypi.com/viewtopic.php?t=369839)
- [V4L2 stateless HEVC - FFmpeg/OpenCV](https://github.com/opencv/opencv/pull/27453)
- [RPi HEVC decoder driver for mainline kernel](https://www.phoronix.com/news/Raspberry-Pi-HEVC-H265-Decode)
- [VLC memory leak on Pi - RPi Forums](https://forums.raspberrypi.com/viewtopic.php?t=347881)
- [VLC high CPU with image demuxer - RPi-Distro/vlc #29](https://github.com/RPi-Distro/vlc/issues/29)
- [Boot time optimization guide](https://ohyaan.github.io/tips/raspberry_pi_boot_time_optimization__complete_performance_guide/)
- [Plymouth splash on Bookworm](https://forums.raspberrypi.com/viewtopic.php?t=366046)
- [Custom splash screen](https://forums.raspberrypi.com/viewtopic.php?t=197472)
- [mpv vo.rst documentation](https://github.com/mpv-player/mpv/blob/master/DOCS/man/vo.rst)
- [Digital picture frame Bookworm Wayland 2025](https://www.thedigitalpictureframe.com/how-to-build-the-best-raspberry-pi-digital-picture-frame-with-bookworm-wayland-2025-edition-pi-2-3-4-5/)
- [mpv slideshow issue #3880](https://github.com/mpv-player/mpv/issues/3880)
- [Baeldung: view media without graphical env](https://www.baeldung.com/linux/view-media-no-graphical-env)
