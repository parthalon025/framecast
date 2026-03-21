#!/bin/bash
# Build FrameCast OS image using pi-gen
#
# Usage:
#   ./build.sh                 # Full build (native, requires sudo)
#   ./build.sh --base-only     # OS-only image (skip FrameCast app)
#   ./build.sh --continue      # Add app layer to existing base (~5 min)
#   ./build.sh --app-only      # Rebuild ONLY the app stage (fastest iteration)
#   ./build.sh --docker        # Full build via Docker
#   ./build.sh --clean         # Wipe work/ and deploy/ before building
#
# Iteration workflow:
#   1. ./build.sh --base-only     → base OS image (~30 min, once)
#   2. [validate FrameCast app]
#   3. ./build.sh --continue      → add app layer (~5 min)
#   4. [make changes]
#   5. ./build.sh --app-only      → rebuild app only (~3 min)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"
USE_DOCKER=0
BASE_ONLY=0
CONTINUE=0
APP_ONLY=0
CLEAN=0

for arg in "$@"; do
    case "$arg" in
        --docker)    USE_DOCKER=1 ;;
        --base-only) BASE_ONLY=1 ;;
        --continue)  CONTINUE=1 ;;
        --app-only)  APP_ONLY=1 ;;
        --clean)     CLEAN=1 ;;
        -h|--help)
            sed -n '2,/^set /{ /^#/s/^# \?//p }' "$0"
            exit 0 ;;
        *)  echo "Unknown option: $arg (try --help)"; exit 1 ;;
    esac
done

# Clone pi-gen if not present (bookworm-arm64 for 64-bit Pi 3/4/5)
if [ ! -d "$PIGEN_DIR" ]; then
    echo "Cloning pi-gen (bookworm-arm64)..."
    git clone --depth 1 --branch bookworm-arm64 \
        https://github.com/RPi-Distro/pi-gen.git "$PIGEN_DIR"
fi

# Copy config into pi-gen (IMG_NAME stays "FrameCast" for work dir consistency)
FRAMECAST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FC_VERSION=$(cat "${FRAMECAST_ROOT}/VERSION" 2>/dev/null || echo "dev")
cp "${SCRIPT_DIR}/config" "${PIGEN_DIR}/config"
echo "Building FrameCast v${FC_VERSION}"
rm -rf "${PIGEN_DIR}/stage2-framecast"
cp -r "${SCRIPT_DIR}/stage2-framecast" "${PIGEN_DIR}/stage2-framecast"

# Skip image export from stages 0-2 (only export from our stage)
for stage in stage0 stage1 stage2; do
    mkdir -p "${PIGEN_DIR}/${stage}"
    touch "${PIGEN_DIR}/${stage}/SKIP_IMAGES"
done

# --- Mode: --base-only ---
if [ "$BASE_ONLY" -eq 1 ]; then
    echo "BASE_ONLY: skipping 02-app (FrameCast app deployment)"
    touch "${PIGEN_DIR}/stage2-framecast/02-app/SKIP"
fi

# Find existing rootfs (work dir name matches IMG_NAME from config)
find_rootfs() {
    local found
    found=$(find "${PIGEN_DIR}/work" -maxdepth 3 -type d -name rootfs -path "*/stage2-framecast/*" 2>/dev/null | head -1)
    echo "${found:-}"
}

# --- Mode: --app-only (fastest iteration) ---
# Skip stages 0-2 entirely + our 00-packages, 01-config, 03-system.
# Only runs 02-app on the existing rootfs.
if [ "$APP_ONLY" -eq 1 ]; then
    ROOTFS="$(find_rootfs)"
    if [ -z "$ROOTFS" ]; then
        echo "ERROR: No rootfs found. Run a full build first."
        exit 1
    fi
    echo "APP_ONLY: reusing $(dirname "$(dirname "$ROOTFS")")"
    for stage in stage0 stage1 stage2; do
        touch "${PIGEN_DIR}/${stage}/SKIP"
    done
    touch "${PIGEN_DIR}/stage2-framecast/00-packages/SKIP"
    touch "${PIGEN_DIR}/stage2-framecast/01-config/SKIP"
    touch "${PIGEN_DIR}/stage2-framecast/03-system/SKIP"
    rm -f "${PIGEN_DIR}/stage2-framecast/02-app/SKIP"
    CONTINUE=1
fi

# --- Mode: --continue ---
if [ "$CONTINUE" -eq 1 ] && [ "$APP_ONLY" -eq 0 ]; then
    ROOTFS="$(find_rootfs)"
    if [ -z "$ROOTFS" ]; then
        echo "ERROR: No existing rootfs found."
        echo "Run './build.sh --base-only' first."
        exit 1
    fi
    echo "CONTINUE: resuming from $(dirname "$(dirname "$ROOTFS")")"
    rm -f "${PIGEN_DIR}/stage2-framecast/02-app/SKIP"
fi

# --- Pre-build frontend on host (runs as user, not sudo) ---
# sudo resets PATH so npm/node are unreachable inside pi-gen.
# Build here where user's PATH works, stage 01-run.sh copies the output.
FRONTEND_DIR="${FRAMECAST_ROOT}/app/frontend"
if [ "$BASE_ONLY" -eq 0 ] && [ -f "${FRONTEND_DIR}/package.json" ]; then
    echo "=== Pre-building frontend (host-native, npm $(npm --version)) ==="
    (
        cd "${FRONTEND_DIR}"
        npm install 2>&1 | tail -3
        npm run build
    )
    echo "Frontend dist/ ready ($(du -sh "${FRONTEND_DIR}/dist" 2>/dev/null | cut -f1 || echo '?'))"
fi

cd "$PIGEN_DIR" || {
    echo "ERROR: Cannot cd to $PIGEN_DIR — did git clone fail?"
    exit 1
}

if [ "$CLEAN" -eq 1 ]; then
    echo "Cleaning previous build artifacts..."
    sudo rm -rf work/ deploy/
fi

if [ "$USE_DOCKER" -eq 1 ]; then
    ./build-docker.sh
else
    if [ "$CONTINUE" -eq 1 ] || [ "$APP_ONLY" -eq 1 ]; then
        sudo CONTINUE=1 ./build.sh
    else
        sudo ./build.sh
    fi
fi

# --- Cleanup app-only SKIP files so next full build works ---
if [ "$APP_ONLY" -eq 1 ]; then
    for stage in stage0 stage1 stage2; do
        rm -f "${PIGEN_DIR}/${stage}/SKIP"
    done
    rm -f "${PIGEN_DIR}/stage2-framecast/00-packages/SKIP"
    rm -f "${PIGEN_DIR}/stage2-framecast/01-config/SKIP"
    rm -f "${PIGEN_DIR}/stage2-framecast/03-system/SKIP"
fi

# --- Rename output with version (skip if already versioned) ---
DEPLOY="${PIGEN_DIR}/deploy"
if [ -d "$DEPLOY" ]; then
    for f in "${DEPLOY}"/*FrameCast*; do
        [ -f "$f" ] || continue
        # Skip if already contains version string
        case "$f" in *"-v${FC_VERSION}"*) continue ;; esac
        versioned="${f/FrameCast/FrameCast-v${FC_VERSION}}"
        sudo mv "$f" "$versioned"
    done
    echo "=== Output ==="
    ls -lh "${DEPLOY}/"
fi
