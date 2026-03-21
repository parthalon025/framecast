#!/bin/bash -e
set -u -o pipefail
# Copy application files into rootfs.
# Frontend is pre-built by wrapper build.sh (runs as user with npm on PATH).
# Output lands in app/static/ which is included in the cp -r below.
: "${ROOTFS_DIR:?ROOTFS_DIR must be set by pi-gen runner}"
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

# Verify pre-built frontend assets exist
if [ -f "${ROOTFS_DIR}/opt/framecast/app/static/js/app.js" ]; then
    echo "Frontend assets: $(du -sh "${ROOTFS_DIR}/opt/framecast/app/static" | cut -f1)"
else
    echo "ERROR: frontend not pre-built — run 'cd app/frontend && npm install && npm run build' first"
    exit 1
fi

# Remove node_modules + frontend source from rootfs (save ~100MB image space)
rm -rf "${ROOTFS_DIR}/opt/framecast/app/frontend/node_modules"
rm -rf "${ROOTFS_DIR}/opt/framecast/app/frontend/src"

# Remove any __pycache__ dirs copied in with app source (R)
find "${ROOTFS_DIR}/opt/framecast" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Pre-download arm64 Python wheels on HOST ---
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
    echo "NOTE: wheel pre-download incomplete — chroot pip will handle remaining"
}

# --- Initialize git repo for OTA updates ---
VERSION=$(cat "${FRAMECAST_SRC}/VERSION")
GITHUB_OWNER=$(grep "^GITHUB_OWNER=" "${FRAMECAST_SRC}/app/.env.example" 2>/dev/null | cut -d= -f2- || echo "parthalon025")
GITHUB_REPO=$(grep "^GITHUB_REPO=" "${FRAMECAST_SRC}/app/.env.example" 2>/dev/null | cut -d= -f2- || echo "framecast")
GITHUB_OWNER="${GITHUB_OWNER:-parthalon025}"
GITHUB_REPO="${GITHUB_REPO:-framecast}"

cd "${ROOTFS_DIR}/opt/framecast"
if [ ! -d .git ]; then
    git init
    git remote add origin "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git"
fi
git config user.email "framecast@local"
git config user.name "FrameCast"
git add -A
git diff --cached --quiet || git commit -m "FrameCast v${VERSION}"
git tag -f "v${VERSION}"
cd -

# --- Install systemd services ---
for svc in framecast.service framecast-kiosk.service wifi-manager.service framecast-update.service framecast-update.timer framecast-health.service framecast-health.timer framecast-schedule.service framecast-schedule.timer framecast-hostname.service; do
    install -m 644 "${FRAMECAST_SRC}/systemd/${svc}" "${ROOTFS_DIR}/etc/systemd/system/"
done

echo "=== FrameCast app: host-side setup complete ==="
