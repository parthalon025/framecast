#!/bin/bash -e
set -u -o pipefail
# SD card longevity and system hardening

: "${ROOTFS_DIR:?ROOTFS_DIR must be set by pi-gen runner}"

# Journal limits
mkdir -p "${ROOTFS_DIR}/etc/systemd/journald.conf.d"
install -m 644 files/framecast-journal.conf "${ROOTFS_DIR}/etc/systemd/journald.conf.d/"

# tmpfs for /tmp
if ! grep -q "^tmpfs.*/tmp" "${ROOTFS_DIR}/etc/fstab"; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,nodev,size=100M 0 0" >> "${ROOTFS_DIR}/etc/fstab"
fi

# noatime on root filesystem
sed -i '/^\(\/dev\/\|PARTUUID=\).*\s\+\/\s\+ext4/ s/defaults/defaults,noatime/' "${ROOTFS_DIR}/etc/fstab" 2>/dev/null || true

# Mask getty on tty1 — kiosk service takes the VT directly, no login prompt
ln -sf /dev/null "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service"

# Watchdog config
install -m 644 files/watchdog.conf "${ROOTFS_DIR}/etc/watchdog.conf"

# Firewall setup script (executed inside chroot by 01-run-chroot.sh)
install -m 755 files/ufw-setup.sh "${ROOTFS_DIR}/usr/local/bin/ufw-setup.sh"

# First-boot hostname script (generates unique hostname from MAC address)
install -m 755 files/framecast-hostname.sh "${ROOTFS_DIR}/usr/local/bin/framecast-hostname.sh"

# Avahi mDNS service advertisement (frame discovery)
mkdir -p "${ROOTFS_DIR}/etc/avahi/services"
install -m 644 files/framecast.service "${ROOTFS_DIR}/etc/avahi/services/framecast.service"

# Create /var/lib/framecast for rollback tags and update state
mkdir -p "${ROOTFS_DIR}/var/lib/framecast"
chown 1000:1000 "${ROOTFS_DIR}/var/lib/framecast"
chmod 700 "${ROOTFS_DIR}/var/lib/framecast"
