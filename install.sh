#!/bin/bash
# DEPRECATED (I8): install.sh is the v1 manual installer for "Pi Photo Display".
# FrameCast v2+ uses pi-gen to produce a pre-built OS image — flash and boot, no installer needed.
# Build a fresh image: cd pi-gen && ./build.sh
# This file is retained for reference only and will be removed in a future release.
echo "WARNING: install.sh is deprecated. Use pi-gen/build.sh to build a FrameCast OS image instead." >&2
exit 1

# install.sh - Pi Photo Display installer for Raspberry Pi OS
# Run as: sudo bash install.sh
set -euo pipefail

INSTALL_DIR="/opt/pi-photo-display"
SCRIPT_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  Pi Photo Display - Installer"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root: sudo bash install.sh"
    exit 1
fi

# Detect user (Pi OS Bookworm removed default 'pi' user)
PI_USER="${SUDO_USER:-}"
if [ -z "$PI_USER" ] || [ "$PI_USER" = "root" ]; then
    PI_USER=$(logname 2>/dev/null || true)
fi
if [ -z "$PI_USER" ] || [ "$PI_USER" = "root" ]; then
    echo "ERROR: Could not detect non-root user."
    echo "Run with: sudo bash install.sh"
    exit 1
fi

PI_HOME=$(getent passwd "$PI_USER" | cut -d: -f6)
MEDIA_DIR="${PI_HOME}/media"

echo "Detected user: $PI_USER (home: $PI_HOME)"
echo ""

echo "[1/10] Updating system packages..."
apt-get update -qq

echo "[2/10] Installing dependencies..."
apt-get install -y -qq \
    vlc-bin \
    vlc-plugin-base \
    python3-flask \
    ffmpeg \
    xdotool \
    xset \
    watchdog \
    zenity \
    qrencode \
    avahi-daemon \
    2>&1 | tail -5

echo "[3/10] Setting up application..."
mkdir -p "$INSTALL_DIR"

# Preserve existing .env config on re-install
if [ -f "$INSTALL_DIR/app/.env" ]; then
    cp "$INSTALL_DIR/app/.env" "/tmp/pi-photo-display-env.bak"
    echo "  Backed up existing .env"
fi

cp -r "$SCRIPT_SOURCE/app" "$INSTALL_DIR/"
cp "$SCRIPT_SOURCE/requirements.txt" "$INSTALL_DIR/"

# Restore or create .env
if [ -f "/tmp/pi-photo-display-env.bak" ]; then
    cp "/tmp/pi-photo-display-env.bak" "$INSTALL_DIR/app/.env"
    rm -f "/tmp/pi-photo-display-env.bak"
    echo "  Restored existing .env config"
elif [ ! -f "$INSTALL_DIR/app/.env" ]; then
    cp "$INSTALL_DIR/app/.env.example" "$INSTALL_DIR/app/.env"
    # Set media dir for detected user
    sed -i "s|^MEDIA_DIR=.*|MEDIA_DIR=$MEDIA_DIR|" "$INSTALL_DIR/app/.env"
    # Generate a secret key
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(24))")
    sed -i "s|^FLASK_SECRET_KEY=.*|FLASK_SECRET_KEY=$SECRET|" "$INSTALL_DIR/app/.env"
    echo "  Created .env with defaults"
fi

# Create media directory
mkdir -p "$MEDIA_DIR"
chown -R "$PI_USER:$PI_USER" "$MEDIA_DIR"
chown -R "$PI_USER:$PI_USER" "$INSTALL_DIR"

# Make scripts executable
chmod +x "$INSTALL_DIR/app/slideshow.sh"
chmod +x "$INSTALL_DIR/app/hdmi-control.sh"

echo "[4/10] Installing systemd services..."

cat > /etc/systemd/system/slideshow.service << SEOF
[Unit]
Description=Pi Photo Display - Slideshow
After=graphical.target
Wants=graphical.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
NotifyAccess=all
User=$PI_USER
Group=$PI_USER
Environment=DISPLAY=:0
Environment=XAUTHORITY=$PI_HOME/.Xauthority
ExecStart=/bin/bash $INSTALL_DIR/app/slideshow.sh
Restart=always
RestartSec=10
KillMode=control-group
TimeoutStopSec=15
WatchdogSec=120
ProtectSystem=full
ReadWritePaths=$MEDIA_DIR
NoNewPrivileges=true
PrivateTmp=true
MemoryMax=512M
MemoryHigh=400M
Nice=-5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical.target
SEOF

cat > /etc/systemd/system/photo-upload.service << WEOF
[Unit]
Description=Pi Photo Display - Web Upload Server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10
ConditionPathIsDirectory=$INSTALL_DIR/app

[Service]
Type=simple
User=$PI_USER
Group=$PI_USER
WorkingDirectory=$INSTALL_DIR/app
ExecStart=/usr/bin/python3 $INSTALL_DIR/app/web_upload.py
Restart=always
RestartSec=5
KillMode=control-group
TimeoutStopSec=10
ProtectSystem=strict
ReadWritePaths=$MEDIA_DIR $INSTALL_DIR/app
NoNewPrivileges=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
MemoryMax=256M
MemoryHigh=200M
Nice=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
WEOF

# Scoped sudoers for slideshow restart only
SUDOERS_TMP=$(mktemp)
echo "$PI_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart slideshow" > "$SUDOERS_TMP"
if visudo -cf "$SUDOERS_TMP" >/dev/null 2>&1; then
    cp "$SUDOERS_TMP" /etc/sudoers.d/pi-photo-display
    chmod 440 /etc/sudoers.d/pi-photo-display
else
    echo "WARNING: sudoers validation failed, skipping. Slideshow restart from web UI may not work."
fi
rm -f "$SUDOERS_TMP"

# Allow reboot/shutdown from web UI
SUDOERS_TMP2=$(mktemp)
echo "$PI_USER ALL=(ALL) NOPASSWD: /usr/sbin/reboot, /usr/sbin/shutdown" > "$SUDOERS_TMP2"
if visudo -cf "$SUDOERS_TMP2" >/dev/null 2>&1; then
    cat "$SUDOERS_TMP2" >> /etc/sudoers.d/pi-photo-display
fi
rm -f "$SUDOERS_TMP2"

systemctl daemon-reload
systemctl enable slideshow.service
systemctl enable photo-upload.service

echo "[5/10] Configuring auto-boot and recovery..."

# Enable auto-login to desktop (required for display output)
if command -v raspi-config &>/dev/null; then
    # B4 = Desktop Autologin
    raspi-config nonint do_boot_behaviour B4 2>/dev/null || true
    echo "  Auto-login to desktop enabled"
fi

# Enable hardware watchdog timer - reboots Pi if system hangs
if [ -f /etc/watchdog.conf ]; then
    cp /etc/watchdog.conf "/etc/watchdog.conf.bak.$(date +%Y%m%d%H%M%S)"
fi
cat > /etc/watchdog.conf << 'WDEOF'
# Hardware watchdog - reboots if system becomes unresponsive
watchdog-device = /dev/watchdog
watchdog-timeout = 15
max-load-1 = 24
interval = 10
WDEOF

# Load the hardware watchdog kernel module on boot
if ! grep -q "^bcm2835_wdt" /etc/modules 2>/dev/null; then
    echo "bcm2835_wdt" >> /etc/modules
fi

# Enable and start the watchdog service
systemctl enable watchdog 2>/dev/null || true
systemctl start watchdog 2>/dev/null || true
echo "  Hardware watchdog enabled (auto-reboot on system hang)"

# Recovery: hardware watchdog + systemd auto-restart handles all crash scenarios
# Power loss: Pi boots automatically when power is restored (default behavior)
echo "  Recovery stack: systemd restart -> hardware watchdog -> auto-reboot"

# --- SD Card Longevity ---
# Limit journal size to prevent SD card fill
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/pi-photo-display.conf << 'JEOF'
[Journal]
SystemMaxUse=50M
SystemMaxFileSize=10M
MaxRetentionSec=7day
JEOF
systemctl restart systemd-journald 2>/dev/null || true

# Mount /tmp as tmpfs to reduce SD card writes
if ! grep -q "^tmpfs.*/tmp" /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,nodev,size=100M 0 0" >> /etc/fstab
    echo "  /tmp mounted as tmpfs (RAM disk)"
fi

# Add noatime to root filesystem to reduce SD card writes
if grep -q "^/dev/\|^PARTUUID=" /etc/fstab; then
    sed -i '/^\(\/dev\/\|PARTUUID=\).*\s\+\/\s\+ext4/ s/defaults/defaults,noatime/' /etc/fstab 2>/dev/null || true
    echo "  noatime added to root filesystem"
fi

# Set .env permissions (contains secret key)
chmod 600 "$INSTALL_DIR/app/.env"
chown "$PI_USER:$PI_USER" "$INSTALL_DIR/app/.env"

echo ""
echo "[6/10] Configuring display settings..."

# Disable screen blanking in lightdm if present
if [ -f /etc/lightdm/lightdm.conf ]; then
    cp /etc/lightdm/lightdm.conf "/etc/lightdm/lightdm.conf.bak.$(date +%Y%m%d%H%M%S)"
    if ! grep -q "xserver-command" /etc/lightdm/lightdm.conf; then
        sed -i '/^\[Seat:\*\]/a xserver-command=X -s 0 -dpms' /etc/lightdm/lightdm.conf
    fi
fi

# Disable screen blanking (0 = disable blanking)
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_blanking 0 2>/dev/null || true
fi

echo "[7/10] Configuring GPU memory..."

# Only set gpu_mem on Pi 3 and older
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
if [[ "$PI_MODEL" == *"Pi 3"* ]] || [[ "$PI_MODEL" == *"Pi 2"* ]] || [[ "$PI_MODEL" == *"Pi 1"* ]]; then
    CONFIG_FILE=""
    if [ -f /boot/config.txt ]; then
        CONFIG_FILE="/boot/config.txt"
    elif [ -f /boot/firmware/config.txt ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
    fi

    if [ -n "$CONFIG_FILE" ]; then
        cp "$CONFIG_FILE" "${CONFIG_FILE}.bak.$(date +%Y%m%d%H%M%S)"
        if ! grep -q "^gpu_mem=" "$CONFIG_FILE"; then
            echo "gpu_mem=128" >> "$CONFIG_FILE"
            echo "  Set GPU memory to 128MB for $PI_MODEL"
        fi
    fi
else
    echo "  Skipping gpu_mem (not needed for $PI_MODEL)"
fi

echo "[8/10] Setting up HDMI schedule..."

# Read HDMI schedule from .env
SCHEDULE_ENABLED=$(grep "^HDMI_SCHEDULE_ENABLED=" "$INSTALL_DIR/app/.env" | cut -d= -f2 | tr -d '[:space:]')

if [ "$SCHEDULE_ENABLED" = "yes" ]; then
    OFF_TIME=$(grep "^HDMI_OFF_TIME=" "$INSTALL_DIR/app/.env" | cut -d= -f2 | tr -d '[:space:]')
    ON_TIME=$(grep "^HDMI_ON_TIME=" "$INSTALL_DIR/app/.env" | cut -d= -f2 | tr -d '[:space:]')
    OFF_HOUR=$(echo "$OFF_TIME" | cut -d: -f1)
    OFF_MIN=$(echo "$OFF_TIME" | cut -d: -f2)
    ON_HOUR=$(echo "$ON_TIME" | cut -d: -f1)
    ON_MIN=$(echo "$ON_TIME" | cut -d: -f2)

    # Validate
    if [[ "$OFF_HOUR" =~ ^[0-9]{1,2}$ ]] && [ "$OFF_HOUR" -le 23 ] &&
       [[ "$OFF_MIN" =~ ^[0-9]{1,2}$ ]] && [ "$OFF_MIN" -le 59 ] &&
       [[ "$ON_HOUR" =~ ^[0-9]{1,2}$ ]] && [ "$ON_HOUR" -le 23 ] &&
       [[ "$ON_MIN" =~ ^[0-9]{1,2}$ ]] && [ "$ON_MIN" -le 59 ]; then
        (crontab -u "$PI_USER" -l 2>/dev/null | grep -v "hdmi-control"; \
         echo "$OFF_MIN $OFF_HOUR * * * $INSTALL_DIR/app/hdmi-control.sh off > /dev/null 2>&1"; \
         echo "$ON_MIN $ON_HOUR * * * $INSTALL_DIR/app/hdmi-control.sh on > /dev/null 2>&1") | crontab -u "$PI_USER" -
        echo "  HDMI schedule: off at $OFF_TIME, on at $ON_TIME"
    else
        echo "  WARNING: Invalid HDMI schedule times, skipping"
    fi
else
    echo "  HDMI schedule disabled"
fi

echo "[9/10] Setting up WiFi AP fallback..."

# Source the WiFi AP fallback installer
if [ -f "$SCRIPT_SOURCE/app/wifi-setup-install.sh" ]; then
    source "$SCRIPT_SOURCE/app/wifi-setup-install.sh"
else
    echo "  WiFi AP fallback script not found, skipping"
fi

echo "[10/10] Setting up welcome screen and network discovery..."

# Set up mDNS so the Pi is accessible at photoframe.local
HOSTNAME_TARGET="photoframe"
hostnamectl set-hostname "$HOSTNAME_TARGET" 2>/dev/null || true
# Configure avahi for .local discovery
cat > /etc/avahi/services/pi-photo-display.service << 'AVEOF'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>Pi Photo Display</name>
  <service>
    <type>_http._tcp</type>
    <port>8080</port>
  </service>
</service-group>
AVEOF
systemctl enable avahi-daemon 2>/dev/null || true
systemctl restart avahi-daemon 2>/dev/null || true
echo "  Device accessible at http://${HOSTNAME_TARGET}.local:8080"

# Generate the welcome screen shown when no photos are loaded
cat > "$INSTALL_DIR/app/generate-welcome.sh" << 'GWEOF'
#!/bin/bash
# generate-welcome.sh - Creates a welcome screen with QR code and setup instructions
# Called by slideshow.sh when no media files are found
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WELCOME_IMG="${SCRIPT_DIR}/static/welcome.png"
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
HOSTNAME=$(hostname 2>/dev/null || echo "photoframe")
URL="http://${IP_ADDR:-${HOSTNAME}.local}:8080"
QR_FILE="/tmp/pi-photo-qr.png"

# Generate QR code pointing to the web UI
if command -v qrencode &>/dev/null; then
    qrencode -o "$QR_FILE" -s 10 -m 2 --foreground=ffffff --background=000000 "$URL" 2>/dev/null || true
fi

# Build welcome screen using ImageMagick (convert) or Python
if command -v python3 &>/dev/null; then
    python3 - "$WELCOME_IMG" "$URL" "$QR_FILE" << 'PYEOF'
import sys, os
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit(0)

out_path = sys.argv[1]
url = sys.argv[2]
qr_path = sys.argv[3]

W, H = 1920, 1080
img = Image.new('RGB', (W, H), color=(15, 17, 23))
draw = ImageDraw.Draw(img)

# Try to load a nice font, fall back to default
font_paths = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf',
]
def load_font(size):
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()

title_font = load_font(72)
body_font = load_font(36)
url_font = load_font(42)
small_font = load_font(24)

y = 120

# Title
draw.text((W//2, y), "Welcome to Pi Photo Display", fill=(88, 166, 255),
          font=title_font, anchor="mt")
y += 120

# Instructions
lines = [
    "To add your photos and videos:",
    "",
    "1. Connect your phone to the same WiFi network",
    "2. Scan the QR code below, or open this link:",
]
for line in lines:
    draw.text((W//2, y), line, fill=(225, 228, 232), font=body_font, anchor="mt")
    y += 50

y += 20
# URL
draw.text((W//2, y), url, fill=(63, 185, 80), font=url_font, anchor="mt")
y += 80

# QR code
if os.path.exists(qr_path):
    try:
        qr = Image.open(qr_path).resize((280, 280), Image.NEAREST)
        qr_x = (W - 280) // 2
        img.paste(qr, (qr_x, y))
        y += 300
    except Exception:
        y += 20

y += 40
draw.text((W//2, y), "Your photos will appear here automatically",
          fill=(139, 148, 158), font=small_font, anchor="mt")

os.makedirs(os.path.dirname(out_path), exist_ok=True)
img.save(out_path)
PYEOF
fi

echo "$WELCOME_IMG"
GWEOF
chmod +x "$INSTALL_DIR/app/generate-welcome.sh"

# Install Pillow for welcome screen generation
pip3 install --break-system-packages -q Pillow 2>/dev/null || pip3 install -q Pillow 2>/dev/null || true

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
IP_ADDR="${IP_ADDR:-<your-pi-ip>}"

echo ""
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo ""
echo "  Your photo display is ready."
echo ""
echo "  To add photos, open this link on"
echo "  your phone or computer:"
echo ""
echo "    http://${IP_ADDR}:8080"
echo ""
echo "  Settings:  http://${IP_ADDR}:8080/settings"
echo ""
echo "  The display will start automatically"
echo "  after reboot and recover from crashes."
echo ""
echo "  To shut down for real (not reboot):"
echo "    touch /tmp/.pi-photo-allow-shutdown"
echo "    sudo shutdown now"
echo ""
echo "  Rebooting now..."
echo "========================================"

# Auto-reboot to start everything
reboot
