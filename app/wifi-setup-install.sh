#!/bin/bash
# wifi-setup-install.sh - Install steps for WiFi AP fallback
#
# Sourced from the main install.sh to add WiFi AP fallback capability.
# Installs packages, creates the systemd service, and configures
# permissions needed for wifi-manager.sh to run.
#
# Expected variables from parent install.sh:
#   INSTALL_DIR  - e.g. /opt/pi-photo-display
#   PI_USER      - the non-root user running the display
#   PI_HOME      - home directory of PI_USER

set -euo pipefail

echo "[WiFi] Installing AP fallback packages..."

# NetworkManager is the default on Bookworm. Install hostapd + dnsmasq
# as fallback for older systems, and as a dependency either way.
apt-get install -y -qq \
    hostapd \
    dnsmasq \
    2>&1 | tail -3

# On Bookworm+ with NetworkManager, hostapd/dnsmasq system services
# are not needed (nmcli handles everything). Disable them so they
# do not conflict. Our script launches them manually when needed.
systemctl disable hostapd 2>/dev/null || true
systemctl stop hostapd 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true
systemctl stop dnsmasq 2>/dev/null || true

# Unmask hostapd in case it was masked (common on fresh Pi OS installs)
systemctl unmask hostapd 2>/dev/null || true

echo "[WiFi] Making wifi-manager.sh executable..."
chmod +x "$INSTALL_DIR/app/wifi-manager.sh"

echo "[WiFi] Creating wifi-manager systemd service..."

cat > /etc/systemd/system/wifi-manager.service << WMEOF
[Unit]
Description=Pi Photo Display - WiFi AP Fallback Manager
After=network.target NetworkManager.service
Wants=network.target

[Service]
Type=simple
ExecStart=/bin/bash ${INSTALL_DIR}/app/wifi-manager.sh
Restart=always
RestartSec=15

# Run as root because managing network interfaces requires privileges
User=root

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=wifi-manager

# Hardening (limited because we need network control)
ProtectHome=read-only
ProtectKernelModules=true
ProtectControlGroups=true
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
WMEOF

systemctl daemon-reload
systemctl enable wifi-manager.service

echo "[WiFi] AP fallback configured."
echo "  When WiFi is unavailable, the Pi will create a hotspot:"
echo "    SSID:     PiPhotoFrame"
echo "    Password: photoframe"
echo "    Web UI:   http://192.168.4.1:8080"
