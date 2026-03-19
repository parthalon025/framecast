#!/bin/bash
# health-check.sh — Post-update health check with auto-rollback
#
# Runs on boot after an OTA update.  If the core services fail to start,
# rolls back to the previous git tag and reboots.
set -euo pipefail

ROLLBACK_FILE="/tmp/framecast-rollback-tag"
INSTALL_DIR="/opt/framecast"

# Only run if a rollback tag exists (meaning we just updated)
if [ ! -f "$ROLLBACK_FILE" ]; then
    exit 0
fi

PREV_TAG=$(cat "$ROLLBACK_FILE")

# Validate tag format to prevent injection
if ! [[ "$PREV_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "INVALID rollback tag: $PREV_TAG — aborting"
    rm -f "$ROLLBACK_FILE"
    exit 1
fi

echo "Post-update health check. Rollback target: $PREV_TAG"

# Wait for services to come up
sleep 10

# Check services
HEALTHY=true
for svc in framecast framecast-kiosk; do
    if ! systemctl is-active --quiet "$svc"; then
        echo "FAIL: $svc is not active"
        HEALTHY=false
    fi
done

if [[ "$HEALTHY" == "true" ]]; then
    echo "Health check PASSED — update confirmed"
    rm -f "$ROLLBACK_FILE"
    exit 0
fi

# Rollback
echo "Health check FAILED — rolling back to $PREV_TAG"
cd "$INSTALL_DIR" || {
    echo "CRITICAL: Cannot cd to $INSTALL_DIR"
    exit 1
}
if ! git checkout --force "$PREV_TAG" 2>&1; then
    echo "ERROR: git checkout $PREV_TAG failed, trying main"
    if ! git checkout --force main 2>&1; then
        echo "CRITICAL: All rollback attempts failed. Manual intervention required."
        exit 1
    fi
fi
git clean -fd 2>/dev/null || true
rm -f "$ROLLBACK_FILE"
sudo reboot
