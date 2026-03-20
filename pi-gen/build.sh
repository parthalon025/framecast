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

# Copy config and custom stage into pi-gen (cp, not symlink — Docker-safe)
cp "${SCRIPT_DIR}/config" "${PIGEN_DIR}/config"
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

# --- Mode: --app-only (fastest iteration) ---
# Skip stages 0-2 entirely + our 00-packages, 01-config, 03-system.
# Only runs 02-app on the existing rootfs.
if [ "$APP_ONLY" -eq 1 ]; then
    ROOTFS="${PIGEN_DIR}/work/FrameCast/stage2-framecast/rootfs"
    if [ ! -d "$ROOTFS" ]; then
        echo "ERROR: No rootfs found. Run a full build first."
        exit 1
    fi
    echo "APP_ONLY: skipping stages 0-2 + base sub-stages, rebuilding app only"
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
    ROOTFS="${PIGEN_DIR}/work/FrameCast/stage2-framecast/rootfs"
    if [ ! -d "$ROOTFS" ]; then
        echo "ERROR: No existing rootfs at ${ROOTFS}"
        echo "Run './build.sh --base-only' first."
        exit 1
    fi
    echo "CONTINUE: resuming build (reusing cached rootfs)"
    rm -f "${PIGEN_DIR}/stage2-framecast/02-app/SKIP"
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
