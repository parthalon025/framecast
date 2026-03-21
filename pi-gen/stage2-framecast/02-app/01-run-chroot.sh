#!/bin/bash -e
set -u -o pipefail
# Runs inside the chroot (Pi filesystem).
# Frontend is already built on the host — this script only does things
# that require the arm64 chroot (service enablement, pip, firewall).

# Enable services
systemctl enable framecast.service
systemctl enable framecast-kiosk.service
systemctl enable wifi-manager.service
systemctl enable framecast-update.timer
systemctl enable framecast-health.timer
systemctl enable framecast-schedule.timer
systemctl enable framecast-hostname.service
systemctl enable avahi-daemon.service
systemctl enable watchdog.service

# getty@tty1 is masked in 03-system — kiosk service owns the VT directly

# Create media directory
mkdir -p /home/pi/media
chown -R 1000:1000 /home/pi/media

# SSH disabled by default for security (Issue #4)
systemctl disable ssh

# Lock pi user password (SSH disabled, headless device)
passwd -l pi

# Permissions
chown -R 1000:1000 /opt/framecast
chmod +x /opt/framecast/kiosk/kiosk.sh
chmod +x /opt/framecast/kiosk/browser.js
chmod +x /opt/framecast/scripts/hdmi-control.sh
chmod +x /opt/framecast/scripts/update-check.sh
chmod +x /opt/framecast/scripts/health-check.sh

# Scoped sudoers for service restart and reboot
SUDOERS_TMP=$(mktemp)
trap 'rm -f "${SUDOERS_TMP:-}"' EXIT
echo "pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart framecast, /usr/bin/systemctl restart framecast-kiosk, /usr/bin/systemctl enable --now ssh, /usr/bin/systemctl disable --now ssh, /usr/sbin/reboot, /usr/sbin/shutdown" > "$SUDOERS_TMP"
if visudo -cf "$SUDOERS_TMP" >/dev/null 2>&1; then
    cp "$SUDOERS_TMP" /etc/sudoers.d/framecast
    chmod 440 /etc/sudoers.d/framecast
else
    echo "WARNING: sudoers validation failed, skipping"
fi
rm -f "$SUDOERS_TMP"

# Frontend already built on host — no npm install/build needed here

# Install Python deps — use pre-downloaded wheels if available
if [ -d /opt/framecast/.wheels ] && [ "$(ls -A /opt/framecast/.wheels 2>/dev/null)" ]; then
    echo "Installing Python deps from pre-downloaded wheels..."
    pip3 install --break-system-packages -q \
        --no-index --find-links=/opt/framecast/.wheels \
        -r /opt/framecast/requirements.txt 2>&1 || {
        echo "Wheel install failed, falling back to network pip..."
        pip3 install --break-system-packages -q -r /opt/framecast/requirements.txt
    }
    rm -rf /opt/framecast/.wheels
else
    echo "No pre-downloaded wheels, installing via network..."
    pip3 install --break-system-packages -q -r /opt/framecast/requirements.txt
fi

# Generate .env from example
cp /opt/framecast/app/.env.example /opt/framecast/app/.env
SECRET=$(python3 -c "import secrets; print(secrets.token_hex(24))")
grep -v '^FLASK_SECRET_KEY=' /opt/framecast/app/.env > /opt/framecast/app/.env.tmp || true
printf 'FLASK_SECRET_KEY=%s\n' "$SECRET" >> /opt/framecast/app/.env.tmp
mv /opt/framecast/app/.env.tmp /opt/framecast/app/.env
sed -i "s|^MEDIA_DIR=.*|MEDIA_DIR=/home/pi/media|" /opt/framecast/app/.env
chmod 600 /opt/framecast/app/.env
chown 1000:1000 /opt/framecast/app/.env

# Configure and enable firewall (ufw)
/usr/local/bin/ufw-setup.sh
systemctl enable ufw
