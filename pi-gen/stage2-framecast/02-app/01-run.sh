#!/bin/bash -e
set -u -o pipefail
# Copy application files (clone on host, not in chroot — avoids QEMU git issues)
FRAMECAST_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

mkdir -p "${ROOTFS_DIR}/opt/framecast"
cp -r "${FRAMECAST_SRC}/app" "${ROOTFS_DIR}/opt/framecast/"
cp -r "${FRAMECAST_SRC}/kiosk" "${ROOTFS_DIR}/opt/framecast/"
cp -r "${FRAMECAST_SRC}/scripts" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/requirements.txt" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/VERSION" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/Makefile" "${ROOTFS_DIR}/opt/framecast/"

# Install systemd services
for svc in framecast.service framecast-kiosk.service wifi-manager.service framecast-update.service framecast-update.timer framecast-health.service framecast-health.timer framecast-schedule.service framecast-schedule.timer; do
    install -m 644 "${FRAMECAST_SRC}/systemd/${svc}" "${ROOTFS_DIR}/etc/systemd/system/"
done
