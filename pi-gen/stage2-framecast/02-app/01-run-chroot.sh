#!/bin/bash -e
set -u -o pipefail
# Runs inside the chroot (Pi filesystem)

# Enable services
systemctl enable framecast.service
systemctl enable framecast-kiosk.service
systemctl enable wifi-manager.service
systemctl enable avahi-daemon.service
systemctl enable watchdog.service

# Auto-login on tty1 (for cage kiosk)
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

# Create media directory
mkdir -p /home/pi/media
chown -R 1000:1000 /home/pi/media

# Lock pi user password (SSH disabled, headless device)
passwd -l pi

# Permissions
chown -R 1000:1000 /opt/framecast
chmod +x /opt/framecast/kiosk/kiosk.sh
chmod +x /opt/framecast/kiosk/browser.js
chmod +x /opt/framecast/scripts/hdmi-control.sh

# Scoped sudoers for service restart and reboot
SUDOERS_TMP=$(mktemp)
echo "pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart framecast, /usr/bin/systemctl restart framecast-kiosk, /usr/sbin/reboot, /usr/sbin/shutdown" > "$SUDOERS_TMP"
if visudo -cf "$SUDOERS_TMP" >/dev/null 2>&1; then
    cp "$SUDOERS_TMP" /etc/sudoers.d/framecast
    chmod 440 /etc/sudoers.d/framecast
else
    echo "WARNING: sudoers validation failed, skipping"
fi
rm -f "$SUDOERS_TMP"

# Build frontend (node/npm available in chroot)
cd /opt/framecast/app/frontend
npm install --production
npm run build
rm -rf node_modules  # Save image space

# Install Python deps (pinned from requirements.txt)
pip3 install --break-system-packages -q -r /opt/framecast/requirements.txt

# mDNS service advertisement
mkdir -p /etc/avahi/services
cat > /etc/avahi/services/framecast.service << 'AVAHI'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>FrameCast</name>
  <service>
    <type>_http._tcp</type>
    <port>8080</port>
  </service>
</service-group>
AVAHI

# Generate .env from example
cp /opt/framecast/app/.env.example /opt/framecast/app/.env
SECRET=$(python3 -c "import secrets; print(secrets.token_hex(24))")
# Use printf to avoid sed injection from special characters
grep -v '^FLASK_SECRET_KEY=' /opt/framecast/app/.env > /opt/framecast/app/.env.tmp || true
printf 'FLASK_SECRET_KEY=%s\n' "$SECRET" >> /opt/framecast/app/.env.tmp
mv /opt/framecast/app/.env.tmp /opt/framecast/app/.env
sed -i "s|^MEDIA_DIR=.*|MEDIA_DIR=/home/pi/media|" /opt/framecast/app/.env
chmod 600 /opt/framecast/app/.env
chown 1000:1000 /opt/framecast/app/.env

# .profile for auto-startx equivalent (cage via kiosk service handles this)
cat > /home/pi/.profile << 'PROF'
# FrameCast auto-start is handled by systemd (framecast-kiosk.service)
# This file is kept minimal
PROF
chown 1000:1000 /home/pi/.profile

# Configure and enable firewall (ufw)
/usr/local/bin/ufw-setup.sh
systemctl enable ufw
