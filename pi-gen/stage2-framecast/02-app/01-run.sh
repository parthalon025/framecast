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
cp "${FRAMECAST_SRC}/.gitignore" "${ROOTFS_DIR}/opt/framecast/"

# Initialize git repo for OTA updates.
# Creates a minimal repo with one commit + version tag + GitHub remote.
# updater.py uses git fetch --tags + git checkout <tag> for OTA.
VERSION=$(cat "${FRAMECAST_SRC}/VERSION")
GITHUB_OWNER=$(grep "^GITHUB_OWNER=" "${FRAMECAST_SRC}/app/.env.example" 2>/dev/null | cut -d= -f2- || echo "parthalon025")
GITHUB_REPO=$(grep "^GITHUB_REPO=" "${FRAMECAST_SRC}/app/.env.example" 2>/dev/null | cut -d= -f2- || echo "framecast")
GITHUB_OWNER="${GITHUB_OWNER:-parthalon025}"
GITHUB_REPO="${GITHUB_REPO:-framecast}"

cd "${ROOTFS_DIR}/opt/framecast"
git init
git config user.email "framecast@local"
git config user.name "FrameCast"
git add -A
git commit -m "FrameCast v${VERSION}"
git tag "v${VERSION}"
git remote add origin "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git"
cd -

# Install systemd services
for svc in framecast.service framecast-kiosk.service wifi-manager.service framecast-update.service framecast-update.timer framecast-health.service framecast-health.timer framecast-schedule.service framecast-schedule.timer framecast-hostname.service; do
    install -m 644 "${FRAMECAST_SRC}/systemd/${svc}" "${ROOTFS_DIR}/etc/systemd/system/"
done
