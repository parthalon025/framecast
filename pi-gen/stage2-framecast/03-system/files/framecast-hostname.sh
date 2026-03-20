#!/bin/bash
# Generate unique hostname from MAC address on first boot.
# Appends last 4 hex digits of the primary NIC MAC to "framecast-",
# e.g. framecast-a1b2.local — prevents mDNS collision on multi-frame networks.
#
# Runs once via framecast-hostname.service, then disables itself.
set -euo pipefail

MARKER="/var/lib/framecast/.hostname-set"

# Idempotent — skip if already ran
if [ -f "$MARKER" ]; then
    echo "Hostname already set, skipping."
    exit 0
fi

# Read MAC from eth0, fall back to wlan0, fall back to a zero MAC
MAC=$(cat /sys/class/net/eth0/address 2>/dev/null \
   || cat /sys/class/net/wlan0/address 2>/dev/null \
   || echo "00:00:00:00:00:00")

# Extract last 4 hex characters (strip colons, take last 4)
SUFFIX=$(echo "$MAC" | tr -d ':' | tail -c 5 | head -c 4)
NEW_HOSTNAME="framecast-${SUFFIX}"

echo "Setting hostname to ${NEW_HOSTNAME} (MAC: ${MAC})"

# Set hostname
hostnamectl set-hostname "$NEW_HOSTNAME"

# Update /etc/hosts
if grep -q "127.0.1.1" /etc/hosts; then
    sed -i "s/127.0.1.1.*/127.0.1.1\t${NEW_HOSTNAME}/" /etc/hosts
else
    echo -e "127.0.1.1\t${NEW_HOSTNAME}" >> /etc/hosts
fi

# Update avahi service name to match
if [ -f /etc/avahi/services/framecast.service ]; then
    sed -i "s|<name>.*</name>|<name>${NEW_HOSTNAME}</name>|" /etc/avahi/services/framecast.service
    systemctl restart avahi-daemon.service 2>/dev/null || true
fi

# Mark complete so this never runs again
touch "$MARKER"
echo "Hostname set to ${NEW_HOSTNAME}"
