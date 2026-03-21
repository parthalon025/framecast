#!/bin/bash -e
set -u -o pipefail
# Copy application files and build frontend ON THE HOST (not in chroot).
# This avoids running npm/esbuild under QEMU arm64 emulation.
FRAMECAST_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

echo "=== FrameCast app: copying files ==="

mkdir -p "${ROOTFS_DIR}/opt/framecast"
cp -r "${FRAMECAST_SRC}/app" "${ROOTFS_DIR}/opt/framecast/"
cp -r "${FRAMECAST_SRC}/kiosk" "${ROOTFS_DIR}/opt/framecast/"
cp -r "${FRAMECAST_SRC}/scripts" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/requirements.txt" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/VERSION" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/Makefile" "${ROOTFS_DIR}/opt/framecast/"
cp "${FRAMECAST_SRC}/.gitignore" "${ROOTFS_DIR}/opt/framecast/"

# --- Build frontend on HOST (native speed, not QEMU) ---
# esbuild produces platform-independent JS/CSS — safe to cross-build.
echo "=== FrameCast app: building frontend (host-native) ==="
FRONTEND_DIR="${FRAMECAST_SRC}/app/frontend"
if [ -f "${FRONTEND_DIR}/package.json" ]; then
    (
        cd "${FRONTEND_DIR}"
        npm install --production 2>&1 | tail -3
        npm run build 2>&1 | tail -3
    )
    # Copy built dist/ into rootfs (overwrite the source copy)
    if [ -d "${FRONTEND_DIR}/dist" ]; then
        mkdir -p "${ROOTFS_DIR}/opt/framecast/app/frontend/dist"
        cp -r "${FRONTEND_DIR}/dist/"* "${ROOTFS_DIR}/opt/framecast/app/frontend/dist/"
        echo "Frontend dist/ copied ($(du -sh "${FRONTEND_DIR}/dist" | cut -f1))"
    else
        echo "WARNING: frontend dist/ not found after build"
    fi
    # Remove node_modules from rootfs copy (save ~100MB image space)
    rm -rf "${ROOTFS_DIR}/opt/framecast/app/frontend/node_modules"
else
    echo "WARNING: no package.json — skipping frontend build"
fi

# --- Pre-download arm64 Python wheels on HOST ---
# Avoids pip compile under QEMU. Falls back to chroot pip if wheels fail.
echo "=== FrameCast app: downloading arm64 Python wheels ==="
WHEEL_DIR="${ROOTFS_DIR}/opt/framecast/.wheels"
mkdir -p "${WHEEL_DIR}"
pip3 download \
    --dest "${WHEEL_DIR}" \
    --platform manylinux2014_aarch64 \
    --platform linux_aarch64 \
    --python-version 311 \
    --only-binary=:all: \
    -r "${FRAMECAST_SRC}/requirements.txt" 2>&1 | tail -5 || {
    echo "WARNING: wheel pre-download failed — chroot pip will handle it"
    rm -rf "${WHEEL_DIR}"
}

# --- Initialize git repo for OTA updates ---
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

# --- Install systemd services ---
for svc in framecast.service framecast-kiosk.service wifi-manager.service framecast-update.service framecast-update.timer framecast-health.service framecast-health.timer framecast-schedule.service framecast-schedule.timer framecast-hostname.service; do
    install -m 644 "${FRAMECAST_SRC}/systemd/${svc}" "${ROOTFS_DIR}/etc/systemd/system/"
done

echo "=== FrameCast app: host-side setup complete ==="
