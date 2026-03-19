#!/bin/bash
# Build FrameCast OS image using pi-gen in Docker
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"

# Clone pi-gen if not present
if [ ! -d "$PIGEN_DIR" ]; then
    git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "$PIGEN_DIR"
fi

# Link our config and custom stage
cp "${SCRIPT_DIR}/config" "${PIGEN_DIR}/config"
ln -sfn "${SCRIPT_DIR}/stage2-framecast" "${PIGEN_DIR}/stage2-framecast"

# Skip image export from stages 0-2 (only export from our stage)
for stage in stage0 stage1 stage2; do
    mkdir -p "${PIGEN_DIR}/${stage}"
    touch "${PIGEN_DIR}/${stage}/SKIP_IMAGES"
done

cd "$PIGEN_DIR" || {
    echo "ERROR: Cannot cd to $PIGEN_DIR — did git clone fail?"
    exit 1
}
./build-docker.sh
