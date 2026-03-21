#!/bin/bash -e
set -u -o pipefail
# Boot configuration
: "${ROOTFS_DIR:?ROOTFS_DIR must be set by pi-gen runner}"
install -m 644 files/config.txt "${ROOTFS_DIR}/boot/firmware/config.txt"
install -m 644 files/cmdline.txt "${ROOTFS_DIR}/boot/firmware/cmdline.txt"

# Hardware watchdog
if ! grep -q "^bcm2835_wdt" "${ROOTFS_DIR}/etc/modules" 2>/dev/null; then
    echo "bcm2835_wdt" >> "${ROOTFS_DIR}/etc/modules"
fi
